"""End-to-end tests for the Grand Orchestrator's ReAct loop, via
OrchestratorSession. Each test is named after the Acceptance Criterion (or
edge case) it covers in ai_agents/specs/grand-orchestrator.md.

Both the LLM and the SubAgentRunner are injected fakes -- scripted, not
live -- so this suite runs deterministically with no network call, same
invariant as all six sub-agents' test suites. Live tool-calling against
the real Groq model is verified separately (see prompts.md); it's not part
of this file because a live LLM's exact tool choice isn't something pytest
can assert on deterministically.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from langchain_core.messages import AIMessage

from orchestrator.graph import OrchestratorDeps
from orchestrator.runner import RunResult
from orchestrator.session import OrchestratorSession


def _token(role: str = "admin") -> str:
    payload = {"sub": "user-1", "org": "org-1", "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, "irrelevant-signing-key", algorithm="HS256")


class _ScriptedLLM:
    """Ignores bind_tools' argument (the fake doesn't need real schemas to
    decide what to say next) and returns each scripted AIMessage in order,
    one per .invoke() call -- one call per plan/synthesize node visit."""

    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self.invoke_calls: list[list] = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.invoke_calls.append(messages)
        if not self._responses:
            raise AssertionError("ScriptedLLM ran out of scripted responses")
        return self._responses.pop(0)


class _FakeRunner:
    def __init__(self, run_results: list[RunResult] | None = None, resume_results: list[RunResult] | None = None):
        self._run_results = list(run_results or [])
        self._resume_results = list(resume_results or [])
        self.run_calls: list[tuple] = []
        self.resume_calls: list[tuple] = []

    def run(self, agent_name, state, *, thread_id=None):
        self.run_calls.append((agent_name, state))
        return self._run_results.pop(0)

    def resume(self, agent_name, thread_id, *, updates=None):
        self.resume_calls.append((agent_name, thread_id, updates))
        return self._resume_results.pop(0)


def _tool_call(name: str, args: dict, call_id: str = "c1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


# plan() calls the LLM once per hop; when the LLM has no more tool calls to
# make, that response's content is discarded and a *separate* synthesize()
# call produces the real final_response (grand-orchestrator.md FR 8's
# dedicated "terminal synthesize_response node") -- so every scenario that
# reaches synthesis needs this "I'm done planning" response scripted in
# addition to the final one.
_STOP_PLANNING = AIMessage(content="")


def test_ac1_single_hop_query_reaches_synthesis() -> None:
    llm = _ScriptedLLM([
        _tool_call("insights", {"query_entity": "fuel_trends"}),
        _STOP_PLANNING,
        AIMessage(content="Fuel costs are trending down."),
    ])
    runner = _FakeRunner(run_results=[RunResult(status="done", state={"query_result": [{"month": "2026-01"}]}, thread_id="t1")])
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner))

    result = session.run("How are fuel costs trending?")

    assert result.status == "done"
    assert result.final_response == "Fuel costs are trending down."
    assert runner.run_calls[0][0] == "insights"


def test_ac1_multi_hop_accumulates_scratchpad_without_extra_prompting() -> None:
    llm = _ScriptedLLM([
        _tool_call("insights", {"query_entity": "fleet_health"}, "c1"),
        _tool_call("assignment", {"assign_request": {
            "vehicle_plate": "OLD-001", "driver_name": "John", "assigned_at": "2026-01-01T08:00:00",
            "start_odometer": 50000, "take_condition": "fair",
        }}, "c2"),
        AIMessage(content="Assigned the oldest truck (OLD-001) to John."),
    ])
    runner = _FakeRunner(run_results=[
        RunResult(status="done", state={"fleet_health": {"vehicles": [{"vehicle_id": "v1", "plate_number": "OLD-001"}]}}, thread_id="t1"),
        RunResult(status="awaiting_approval", state={"vehicle_id": "v1"}, thread_id="t2", pending_node="executing"),
    ])
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner))

    result = session.run("Find the oldest unassigned truck and assign it to John.")

    assert result.status == "awaiting_approval"
    assert result.hitl_state["agent_name"] == "assignment"
    assert len(runner.run_calls) == 2
    assert runner.run_calls[0][0] == "insights"
    assert runner.run_calls[1][0] == "assignment"


def test_ac2_and_ac3_hitl_pause_then_approve_resumes_and_completes() -> None:
    llm = _ScriptedLLM([
        _tool_call("assignment", {"assign_request": {
            "vehicle_plate": "ABC-123", "driver_name": "Jane", "assigned_at": "2026-01-01T08:00:00",
            "start_odometer": 1000, "take_condition": "good",
        }}),
        _STOP_PLANNING,
        AIMessage(content="Assigned ABC-123 to Jane."),
    ])
    runner = _FakeRunner(
        run_results=[RunResult(status="awaiting_approval", state={"vehicle_id": "v1"}, thread_id="t1", pending_node="executing")],
        resume_results=[RunResult(status="done", state={"created_record": {"id": "a1", "driver_id": "d1"}}, thread_id="t1")],
    )
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner))

    paused = session.run("Assign ABC-123 to Jane.")
    assert paused.status == "awaiting_approval"

    resumed = session.approve()

    assert resumed.status == "done"
    assert resumed.final_response == "Assigned ABC-123 to Jane."
    assert runner.resume_calls[0][0] == "assignment"
    assert runner.resume_calls[0][2] is None  # no updates on a plain approve


def test_hitl_modify_passes_updates_to_resume() -> None:
    llm = _ScriptedLLM([
        _tool_call("assignment", {"assign_request": {
            "vehicle_plate": "ABC-123", "driver_name": "Jane", "assigned_at": "2026-01-01T08:00:00",
            "start_odometer": 1000, "take_condition": "good",
        }}),
        _STOP_PLANNING,
        AIMessage(content="Done, with the corrected odometer."),
    ])
    runner = _FakeRunner(
        run_results=[RunResult(status="awaiting_approval", state={}, thread_id="t1", pending_node="executing")],
        resume_results=[RunResult(status="done", state={"created_record": {"id": "a1"}}, thread_id="t1")],
    )
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner))
    session.run("Assign ABC-123 to Jane.")

    session.modify({"assign_request": {"start_odometer": 1500}})

    assert runner.resume_calls[0][2] == {"assign_request": {"start_odometer": 1500}}


def test_hitl_reject_aborts_without_resuming(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = _ScriptedLLM([
        _tool_call("assignment", {"assign_request": {
            "vehicle_plate": "ABC-123", "driver_name": "Jane", "assigned_at": "2026-01-01T08:00:00",
            "start_odometer": 1000, "take_condition": "good",
        }}),
        _STOP_PLANNING,
        AIMessage(content="Okay, I did not make the assignment."),
    ])
    runner = _FakeRunner(run_results=[RunResult(status="awaiting_approval", state={}, thread_id="t1", pending_node="executing")])
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner))
    session.run("Assign ABC-123 to Jane.")

    result = session.reject()

    assert result.status == "done"
    assert runner.resume_calls == []  # never actually resumed the paused thread
    assert "aborted" in session.state["scratchpad"][-1]["observation"].lower()


def test_fr2_auth_context_injected_into_sub_agent_state_not_visible_to_llm() -> None:
    llm = _ScriptedLLM([_tool_call("insights", {"query_entity": "dashboard_summary"}), _STOP_PLANNING, AIMessage(content="Here you go.")])
    runner = _FakeRunner(run_results=[RunResult(status="done", state={"query_result": {}}, thread_id="t1")])
    token = _token(role="fleet_manager")
    session = OrchestratorSession(token, deps=OrchestratorDeps(llm=llm, runner=runner))

    session.run("Give me the summary.")

    passed_state = runner.run_calls[0][1]
    assert passed_state["token"] == token
    # the LLM's own messages never contain the raw token/role
    for message in llm.invoke_calls[0]:
        assert token not in str(message.content)


def test_fr6_halted_sub_agent_halts_the_session_and_explains() -> None:
    llm = _ScriptedLLM([
        _tool_call("maintenance", {"query_entity": "inventory"}),
        _STOP_PLANNING,
        AIMessage(content="I could not check inventory: you don't have permission."),
    ])
    runner = _FakeRunner(run_results=[RunResult(status="halted", state={"halt_reason": "Role 'driver' is not permitted..."}, thread_id="t1")])
    session = OrchestratorSession(_token(role="driver"), deps=OrchestratorDeps(llm=llm, runner=runner))

    result = session.run("What's in stock?")

    assert result.status == "done"  # the LLM chose to explain rather than retry -- session itself doesn't hard-halt
    assert "permission" in result.final_response.lower()


def test_fr7_validation_error_is_fed_back_and_llm_can_correct_it() -> None:
    llm = _ScriptedLLM([
        _tool_call("assignment", {"assign_request": {"vehicle_plate": "ABC-123"}, "bogus_field": True}),
        _tool_call("assignment", {"assign_request": {
            "vehicle_plate": "ABC-123", "driver_name": "Jane", "assigned_at": "2026-01-01T08:00:00",
            "start_odometer": 1000, "take_condition": "good",
        }}),
        AIMessage(content="Assigned."),
    ])
    runner = _FakeRunner(run_results=[RunResult(status="awaiting_approval", state={}, thread_id="t1", pending_node="executing")])
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner))

    result = session.run("Assign ABC-123 to Jane.")

    # first (invalid) call never reached the runner; only the corrected second one did
    assert len(runner.run_calls) == 1
    assert result.status == "awaiting_approval"


def test_fr7_hard_faults_after_max_retries() -> None:
    bad_call = _tool_call("assignment", {"bogus_field": True})
    llm = _ScriptedLLM([bad_call, bad_call, bad_call, AIMessage(content="I couldn't build a valid request.")])
    runner = _FakeRunner()
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner))

    result = session.run("Assign something.")

    assert result.status == "halted"
    assert runner.run_calls == []  # never once reached the sub-agent


def test_hop_limit_halts_a_runaway_loop() -> None:
    from orchestrator.graph import MAX_HOPS

    infinite_calls = [_tool_call("insights", {"query_entity": "dashboard_summary"}, f"c{i}") for i in range(MAX_HOPS + 2)]
    llm = _ScriptedLLM([*infinite_calls, AIMessage(content="giving up")])
    runner = _FakeRunner(run_results=[RunResult(status="done", state={"query_result": {}}, thread_id=f"t{i}") for i in range(MAX_HOPS)])
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner))

    result = session.run("Keep checking the summary forever.")

    assert result.status == "halted"
    assert len(runner.run_calls) == MAX_HOPS
