"""The Grand Orchestrator's routing contract (what the LLM is told) and its graceful
handling of tool failures (a broken tool becomes an observation, never a crashed turn).

The routing tests check the instructions and tool descriptions the model receives; which
tool a live model then picks is verified separately against the real LLM."""

from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from langchain_core.messages import AIMessage

from orchestrator.graph import OrchestratorDeps
from orchestrator.runner import RunResult
from orchestrator.session import OrchestratorSession
from orchestrator.tool_errors import describe_failure
from orchestrator.tool_schemas import MaintenanceToolInput, SearchDocumentsInput
from orchestrator.tools import build_llm_tools
from tools.api_client import BackendAPIError


def _token(role: str = "admin") -> str:
    payload = {"sub": "user-1", "org": "org-1", "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, "irrelevant-signing-key", algorithm="HS256")


class _LLM:
    def __init__(self, responses):
        self.responses, self.seen, self.bound = list(responses), [], []

    def bind_tools(self, tools):
        self.bound = tools
        return self

    def invoke(self, messages):
        self.seen.append(messages)
        return self.responses.pop(0)


class _Runner:
    def __init__(self, *, run=None, resume=None):
        self._run, self._resume = run, resume
        self.calls = []

    def run(self, agent_name, state, *, thread_id=None):
        self.calls.append(agent_name)
        return self._run(agent_name, state)

    def resume(self, agent_name, thread_id, *, updates=None):
        return self._resume(agent_name, thread_id)


class _Retriever:
    def __init__(self, error=None):
        self.error = error

    def search(self, context, query, document_types=None):
        if self.error:
            raise self.error
        return []


def _call(name, args, call_id="c1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def _system_prompt(documents: bool) -> str:
    llm = _LLM([AIMessage(content=""), AIMessage(content="ok")])
    deps = OrchestratorDeps(llm=llm, runner=_Runner(), documents=_Retriever() if documents else None)
    OrchestratorSession(_token(), deps=deps).run("Which vehicles are due for service?")
    return str(llm.seen[0][0].content)


# --- routing contract -----------------------------------------------------------------


def test_the_system_prompt_maps_every_sub_agent_to_its_real_tool_name() -> None:
    prompt = _system_prompt(documents=False)
    for label, tool in [
        ("Fleet Registry", "foundation"),
        ("Fuel Log", "fuel"),
        ("Maintenance & Spare Parts", "maintenance"),
        ("Driver Accountability", "accountability"),
        ("Strategic Insights", "insights"),
        ("Vehicle Assignment", "assignment"),
    ]:
        assert f"{label} (`{tool}`" in prompt, label
    # The tool names the prompt uses are exactly the tools the model is given.
    assert {t.name for t in build_llm_tools()} == {"foundation", "fuel", "maintenance", "accountability", "insights", "assignment"}


def test_the_strict_separation_rule_and_service_due_routing_are_stated() -> None:
    prompt = _system_prompt(documents=True)
    assert "structured operational data, live database records and fleet metrics MUST ALWAYS be routed to the six sub-agents" in prompt
    assert "Never use search_documents for vehicles, odometers, fuel logs, costs, service due dates" in prompt
    assert "which vehicles are due or overdue for service (query_entity=service_due)" in prompt
    assert "manufacturer manuals" in prompt and "safety protocols" in prompt


def test_document_search_rules_appear_only_when_the_tool_is_bound() -> None:
    assert "search_documents" not in _system_prompt(documents=False)
    assert "## Document search" in _system_prompt(documents=True)


def test_prompt_carries_no_copy_paste_citation_artifacts() -> None:
    for prompt in (_system_prompt(documents=True), _system_prompt(documents=False)):
        assert "[cite" not in prompt


def test_tool_descriptions_repeat_the_boundary_where_the_model_chooses_a_tool() -> None:
    doc = SearchDocumentsInput.__doc__ or ""
    assert "NEVER for live operational data" in doc and "service due dates" in doc
    maintenance = MaintenanceToolInput.__doc__ or ""
    assert "ALWAYS use service_due" in maintenance
    assert MaintenanceToolInput(query_entity="service_due").query_entity == "service_due"


# --- graceful tool failures -------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (httpx.ConnectError("[Errno 11002] getaddrinfo failed for internal-host:5432"), "could not be reached"),
        (httpx.ReadTimeout("timed out"), "did not respond in time"),
        (BackendAPIError(503, "Document search temporarily unavailable"), "temporarily unavailable (HTTP 503)"),
        (BackendAPIError(404, "index fleet-documents not found"), "not found (HTTP 404)"),
        (BackendAPIError(403, "forbidden"), "refused access (HTTP 403)"),
        (RuntimeError("psycopg.OperationalError: host=10.0.0.5 password=..."), "unexpected internal error occurred (RuntimeError)"),
    ],
)
def test_failures_are_described_without_leaking_internals(exc, expected) -> None:
    text = describe_failure(exc)
    assert expected in text
    for secret in ("internal-host", "10.0.0.5", "password", "fleet-documents", "getaddrinfo"):
        assert secret not in text


def test_a_sub_agent_that_raises_becomes_an_observation_and_the_turn_still_answers() -> None:
    def boom(agent_name, state):
        raise httpx.ConnectError("connection refused")

    llm = _LLM([_call("maintenance", {"query_entity": "service_due"}), AIMessage(content=""), AIMessage(content="Service data is unavailable right now.")])
    result = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=_Runner(run=boom))).run(
        "Which vehicles are due for service?"
    )

    assert result.status == "done"
    assert result.final_response == "Service data is unavailable right now."
    observation = result.state["scratchpad"][0]["observation"]
    assert observation.startswith("maintenance failed: the backend could not be reached")
    assert "Do not retry it with the same arguments" in observation
    # The failure reached the planner as data it can reason over.
    assert any("maintenance failed" in str(m.content) for m in llm.seen[1])


def test_one_failing_tool_does_not_stop_the_next_one_in_the_same_turn() -> None:
    def run(agent_name, state):
        if agent_name == "maintenance":
            raise BackendAPIError(503, "down")
        return RunResult(status="done", state={"query_result": [{"plate_number": "ABC-123"}]}, thread_id="t2")

    llm = _LLM([
        AIMessage(content="", tool_calls=[
            {"name": "maintenance", "args": {"query_entity": "service_due"}, "id": "c1", "type": "tool_call"},
            {"name": "foundation", "args": {"query_entity": "vehicles"}, "id": "c2", "type": "tool_call"},
        ]),
        AIMessage(content=""),
        AIMessage(content="ABC-123 is registered; service data is unavailable."),
    ])
    runner = _Runner(run=run)
    result = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner)).run("Show vehicles and what's due")

    assert runner.calls == ["maintenance", "foundation"]
    observations = [e["observation"] for e in result.state["scratchpad"]]
    assert observations[0].startswith("maintenance failed:") and observations[1].startswith("foundation succeeded")


def test_a_document_index_outage_is_a_descriptive_observation() -> None:
    llm = _LLM([_call("search_documents", {"query": "tyre pressure"}), AIMessage(content=""), AIMessage(content="The manual search is down.")])
    deps = OrchestratorDeps(llm=llm, runner=_Runner(), documents=_Retriever(error=BackendAPIError(503, "index missing")))
    result = OrchestratorSession(_token(), deps=deps).run("What tyre pressure does the manual specify?")

    assert result.status == "done"
    assert result.state["scratchpad"][0]["observation"].startswith(
        "search_documents failed: the backend service is temporarily unavailable (HTTP 503)"
    )


def test_an_outage_while_resuming_an_approval_is_an_observation_not_a_crash() -> None:
    def paused(agent_name, state):
        return RunResult(status="awaiting_approval", state={}, thread_id="t1", pending_node="executing")

    def boom(agent_name, thread_id):
        raise httpx.ReadTimeout("slow")

    llm = _LLM([
        _call("assignment", {"assign_request": {"vehicle_plate": "ABC-123", "driver_name": "Jane", "assigned_at": "2026-01-01T08:00:00", "start_odometer": 1000, "take_condition": "good"}}),
        AIMessage(content=""),
        AIMessage(content="The assignment could not be confirmed."),
    ])
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=_Runner(run=paused, resume=boom)))
    assert session.run("Assign ABC-123 to Jane").status == "awaiting_approval"

    resumed = session.approve()

    assert resumed.status == "done"
    assert resumed.state["scratchpad"][-1]["observation"].startswith("assignment failed: the backend did not respond in time")
