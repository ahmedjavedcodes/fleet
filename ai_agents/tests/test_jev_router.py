"""Jev as the first decision layer: the request contract, the route decisions, every fallback to the LLM, and the way
the orchestrator uses it (a document question, a lookup or a maintenance note never reaches the planning model; a
write is gated before it runs). Jev is faked at the HTTP layer; nothing touches a network."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from langchain_core.messages import AIMessage

from orchestrator import jev_router as jr
from orchestrator.graph import OrchestratorDeps
from orchestrator.runner import RunResult
from orchestrator.session import OrchestratorSession


def _token(role: str = "admin") -> str:
    return jwt.encode({"sub": "u", "org": "o", "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}, "k", algorithm="HS256")


def route_answer(route, confidence=0.97, lookup=("vehicles", 0.99)):
    return {"route": {"type": "choice", "choice": route, "probabilities": {route: confidence}, "confidence": confidence},
            "lookup_entity": {"type": "choice", "choice": lookup[0], "probabilities": {lookup[0]: lookup[1]}, "confidence": lookup[1]}}


def gate_answer(risk=0.05, missing=("none", 0.99)):
    return {"high_risk": {"type": "noul", "noul": risk}, "missing": {"type": "choice", "choice": missing[0], "confidence": missing[1], "probabilities": {missing[0]: missing[1]}}}


class FakeJev:
    """A JevClient wired to a mock transport: `route` and `gate` are what it answers, `requests` is what it was sent."""

    def __init__(self, route=None, gate=None, status=200, body=None, raises=None):
        self.route, self.gate, self.status, self.body, self.raises = route, gate or gate_answer(), status, body, raises
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        self.client = jr.JevClient("sk-test", client=httpx.Client(transport=httpx.MockTransport(self._handle)))
        self.router = jr.JevRouter(self.client)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if self.raises:
            raise self.raises
        payload = json.loads(request.content)
        self.requests.append(payload)
        self.headers.append(dict(request.headers))
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "nope"})
        if self.body is not None:
            return httpx.Response(200, json=self.body)
        answers = self.route if "route" in payload["questions"] else self.gate
        return httpx.Response(200, json={"answers": answers, "model": "jev-1", "usage": {"input_tokens": 10, "output_tokens": 0}})


def decide(fake, message="hello", role="admin", has_image=False, documents=True):
    return fake.router.route_turn(message, role=role, has_image=has_image, documents_available=documents)


# --- the contract ----------------------------------------------------------------------------------------------


def test_the_request_is_state_model_and_typed_questions_with_a_bearer_key() -> None:
    fake = FakeJev(route=route_answer("complex_reasoning"))

    decide(fake, "Why is fuel up?")

    body, headers = fake.requests[0], fake.headers[0]
    assert set(body) == {"model", "state", "questions"} and body["model"] == "jev-latest"
    assert body["state"]["message"] == "Why is fuel up?" and body["state"]["attachment"] == "none"
    route = body["questions"]["route"]
    assert route["type"] == "choice" and set(route["criteria"]) == {"fuel_log", "maintenance_log", "document_search", "registry_lookup", "complex_reasoning"}
    assert headers["authorization"] == "Bearer sk-test"


def test_the_gate_asks_a_noul_and_a_choice_of_slots_with_none_as_an_option() -> None:
    fake = FakeJev()

    fake.router.gate_write("maintenance", {"document_type": "work_order", "document_text": "x"}, message="x", has_image=False)

    questions = fake.requests[0]["questions"]
    assert questions["high_risk"]["type"] == "noul"
    assert questions["missing"]["type"] == "choice" and "none" in questions["missing"]["criteria"]


# --- the decisions (RBAC, confidence, validity are all checked in code) -----------------------------------------------


def test_a_document_question_goes_straight_to_the_document_search_tool() -> None:
    decision = decide(FakeJev(route=route_answer("document_search")), "What does the manual say about tyres?")

    assert decision.kind == "direct" and decision.call["name"] == "search_documents"
    assert decision.call["args"] == {"query": "What does the manual say about tyres?"}


def test_a_lookup_goes_straight_to_the_registry_with_the_entity_jev_picked() -> None:
    decision = decide(FakeJev(route=route_answer("registry_lookup", lookup=("drivers", 0.9))), "list our drivers")

    assert decision.kind == "direct" and decision.call["name"] == "foundation" and decision.call["args"] == {"query_entity": "drivers"}


def test_a_typed_maintenance_note_goes_straight_to_the_maintenance_tool_as_a_work_order() -> None:
    decision = decide(FakeJev(route=route_answer("maintenance_log")), "Major service for CD-5678,  brake service")

    assert decision.kind == "direct" and decision.call["name"] == "maintenance"
    assert decision.call["args"] == {"document_type": "work_order", "document_text": "Major service for CD-5678, brake service"}


def test_a_fuel_log_keeps_the_planner_but_only_with_the_fuel_and_registry_tools() -> None:
    decision = decide(FakeJev(route=route_answer("fuel_log")), "40 liters for AB-1234")

    assert decision.kind == "restrict" and decision.tools == {"fuel", "foundation"}


@pytest.mark.parametrize(
    ("route", "kwargs"),
    [
        (route_answer("complex_reasoning"), {}),
        (route_answer("made_up_route"), {}),
        (route_answer("document_search", confidence=0.4), {}),
        (route_answer("document_search"), {"documents": False}),
        (route_answer("maintenance_log"), {"role": "driver"}),  # RBAC: the sub-agent's own refusal handles it
        (route_answer("maintenance_log"), {"role": "fleet_manager"}),
        (route_answer("maintenance_log"), {"has_image": True}),  # work order or parts invoice: the planner says which
        (route_answer("registry_lookup", lookup=("other", 0.99)), {}),
        (route_answer("registry_lookup", lookup=("vehicles", 0.3)), {}),
        (route_answer("registry_lookup"), {"role": "mechanic"}),
        ({"route": {"choice": "document_search"}}, {}),  # no confidence at all
        ({}, {}),
    ],
)
def test_anything_doubtful_goes_to_the_llm(route, kwargs) -> None:
    assert decide(FakeJev(route=route), **kwargs).kind == "llm"


@pytest.mark.parametrize(
    "fake",
    [
        FakeJev(raises=httpx.ReadTimeout("slow")),
        FakeJev(status=401), FakeJev(status=429), FakeJev(status=529), FakeJev(status=500),
        FakeJev(body={"unexpected": True}), FakeJev(body={"answers": "nope"}),
    ],
)
def test_every_failure_falls_back_to_the_llm(fake) -> None:
    assert decide(fake).kind == "llm"
    assert fake.router.gate_write("maintenance", {"document_text": "x"}, message="x", has_image=False) == jr.WriteGate()


def test_repeated_failures_stop_the_calls_for_a_while() -> None:
    fake = FakeJev(status=500)

    for _ in range(6):
        decide(fake)

    assert len(fake.requests) == jr.BREAKER_FAILURES  # the rest never left the process


def test_no_key_or_a_switch_means_no_router(monkeypatch) -> None:
    for env, expected in (({"JEV_API_KEY": ""}, False), ({"JEV_API_KEY": "k", "JEV_ENABLED": "off"}, False), ({"JEV_API_KEY": "k"}, True)):
        monkeypatch.delenv("JEV_ENABLED", raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        jr.get_jev_router.cache_clear()
        assert (jr.get_jev_router() is not None) is expected
    jr.get_jev_router.cache_clear()


# --- through a real session -----------------------------------------------------------------------------------------


class _Planner:
    def __init__(self, llm):
        self.llm = llm

    def invoke(self, messages, **kwargs):
        self.llm.planner_calls += 1
        return self.llm.planner_reply


class _LLM:
    """bind_tools(...).invoke is the planner; invoke is the reply writer."""

    def __init__(self, planner_reply=None, reply="Here is the answer."):
        self.planner_reply = planner_reply or AIMessage(content="")
        self.reply, self.planner_calls, self.reply_calls, self.bound = reply, 0, 0, []

    def bind_tools(self, tools):
        self.bound.append(sorted(t.name for t in tools))
        return _Planner(self)

    def invoke(self, messages, **kwargs):
        self.reply_calls += 1
        return AIMessage(content=self.reply)


class _Runner:
    def __init__(self, *results):
        self.calls, self.results = [], list(results)

    def run(self, agent, state, *, thread_id=None):
        self.calls.append((agent, state))
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


class _Retriever:
    def __init__(self):
        self.calls = []

    def search(self, context, query, document_types=None, *, document_ids=None):
        self.calls.append(query)
        return [{"document_id": str(uuid.uuid4()), "filename": "Manual.pdf", "document_type": "manual", "chunk_index": 1, "text": "Check tyre pressure weekly.", "relevance": 0.9}]


def _session(fake, llm, runner=None, role="admin", **deps):
    return OrchestratorSession(_token(role), deps=OrchestratorDeps(llm=llm, runner=runner or _Runner(RunResult(status="done", state={}, thread_id="t")), router=fake.router, **deps))


def test_a_document_question_never_reaches_the_planning_model() -> None:
    llm, retriever = _LLM(reply="Tyre pressure is checked weekly."), _Retriever()
    session = _session(FakeJev(route=route_answer("document_search")), llm, documents=retriever)

    result = session.run("What does the manual say about tyre pressure?")

    assert llm.planner_calls == 0 and llm.reply_calls == 1  # one reply, no planning call
    assert retriever.calls == ["What does the manual say about tyre pressure?"]
    assert result.final_response == "Tyre pressure is checked weekly."


def test_a_registry_lookup_runs_the_tool_without_a_planning_call() -> None:
    llm = _LLM()
    runner = _Runner(RunResult(status="done", state={"query_result": [{"plate_number": "AB-1234"}]}, thread_id="t"))

    _session(FakeJev(route=route_answer("registry_lookup")), llm, runner).run("show me the vehicles")

    assert llm.planner_calls == 0 and [(a, s.get("query_entity")) for a, s in runner.calls] == [("foundation", "vehicles")]


def test_a_complex_question_is_the_ordinary_llm_loop_with_every_tool() -> None:
    llm = _LLM()

    _session(FakeJev(route=route_answer("complex_reasoning")), llm).run("Why did fuel costs rise last month?")

    assert llm.planner_calls == 1 and len(llm.bound[0]) == 6  # the six sub-agents (no memory or document tool in this session)


def test_a_fuel_log_plans_with_only_the_fuel_and_registry_tools() -> None:
    llm = _LLM()

    _session(FakeJev(route=route_answer("fuel_log")), llm).run("Log a fuel fill: 40 liters for AB-1234 at 280 per liter")

    assert llm.bound == [["foundation", "fuel"]] and llm.planner_calls == 1


def test_a_role_not_routed_directly_still_gets_the_llm_path() -> None:
    llm = _LLM()

    _session(FakeJev(route=route_answer("maintenance_log")), llm, role="driver").run("Log a service for CD-5678")

    assert llm.planner_calls == 1


def test_with_jev_down_the_llm_orchestrator_works_exactly_as_before() -> None:
    llm = _LLM(reply="Twelve vehicles.")

    result = _session(FakeJev(raises=httpx.ConnectError("down")), llm).run("How many vehicles do we have?")

    assert llm.planner_calls == 1 and result.final_response == "Twelve vehicles."


# --- the write gate ---------------------------------------------------------------------------------------------------

NOTE = "Major service for CD-5678: brake service and filters Rs 35000"


def _pending() -> RunResult:
    return RunResult(status="awaiting_approval", state={"extracted": {"vehicle_plate": "CD-5678"}}, thread_id="t2", pending_node="creating_log")


def test_a_note_without_a_vehicle_is_asked_for_with_a_fixed_sentence_and_no_model_call() -> None:
    llm, runner = _LLM(), _Runner(_pending())
    fake = FakeJev(route=route_answer("maintenance_log"), gate=gate_answer(missing=("vehicle", 0.95)))

    result = _session(fake, llm, runner).run("brake service and filters Rs 35,000 done today")

    assert runner.calls == [] and llm.planner_calls == 0 and llm.reply_calls == 0  # no sub-agent, no LLM at all
    assert result.final_response == jr.missing_reply(["which vehicle it is for (plate number)"])
    assert result.hitl_state is None


def test_the_answer_to_that_question_is_merged_with_the_note_and_reaches_the_approval_card() -> None:
    llm, runner = _LLM(), _Runner(_pending())
    fake = FakeJev(route=route_answer("maintenance_log"))
    session = _session(fake, llm, runner)
    session.state = {**session.state, "_pending_notes": {"maintenance": "brake service and filters Rs 35,000 done today"}}

    result = session.run("the vehicle was CD-5678")

    assert llm.planner_calls == 0 and llm.reply_calls == 0
    note = runner.calls[0][1]["document_text"]
    assert "brake service and filters" in note and "CD-5678" in note
    assert result.hitl_state is not None and result.hitl_state["agent_name"] == "maintenance"


def test_the_code_overrules_jev_when_it_can_see_the_vehicle_is_there() -> None:
    runner = _Runner(_pending())
    fake = FakeJev(route=route_answer("maintenance_log"), gate=gate_answer(missing=("vehicle", 0.99)))

    result = _session(fake, _LLM(), runner).run(NOTE)

    assert [a for a, _ in runner.calls] == ["maintenance"] and result.hitl_state is not None


def test_a_weak_missing_flag_is_ignored() -> None:
    runner = _Runner(_pending())
    fake = FakeJev(route=route_answer("maintenance_log"), gate=gate_answer(missing=("work_done", 0.5)))

    assert _session(fake, _LLM(), runner).run("service on CD-5678 done").hitl_state is not None


def test_a_high_risk_flag_puts_a_warning_on_the_approval_card_and_never_skips_it() -> None:
    runner = _Runner(_pending())
    fake = FakeJev(route=route_answer("maintenance_log"), gate=gate_answer(risk=0.93))

    result = _session(fake, _LLM(), runner).run(NOTE)

    assert result.hitl_state is not None and result.hitl_state["approval_prompt"].startswith(jr.RISK_NOTICE)


def test_a_normal_write_has_no_warning() -> None:
    result = _session(FakeJev(route=route_answer("maintenance_log")), _LLM(), _Runner(_pending())).run(NOTE)

    assert jr.RISK_NOTICE not in result.hitl_state["approval_prompt"]


def test_a_failed_gate_call_does_not_block_the_write() -> None:
    fake = FakeJev(route=route_answer("maintenance_log"))
    original = fake.client.ask
    fake.client.ask = lambda state, questions: original(state, questions) if "route" in questions else None  # the gate call fails

    assert _session(fake, _LLM(), _Runner(_pending())).run(NOTE).hitl_state is not None


def test_the_gate_never_runs_for_a_read() -> None:
    fake = FakeJev(route=route_answer("registry_lookup"))

    _session(fake, _LLM(), _Runner(RunResult(status="done", state={"query_result": []}, thread_id="t"))).run("list vehicles")

    assert all("high_risk" not in r["questions"] for r in fake.requests)
