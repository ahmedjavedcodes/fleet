"""Proves FleetLiveObserver is actually wired into a real orchestrator run
end-to-end (graph.py + session.py), not just unit-tested in isolation.
"""

from datetime import datetime, timedelta, timezone

import jwt
from langchain_core.messages import AIMessage

from orchestrator.callbacks import FleetLiveObserver
from orchestrator.graph import OrchestratorDeps
from orchestrator.runner import RunResult
from orchestrator.session import OrchestratorSession


def _token(role: str = "admin") -> str:
    payload = {"sub": "user-1", "org": "org-1", "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, "irrelevant-signing-key", algorithm="HS256")


class _ScriptedLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return self._responses.pop(0)


class _FakeRunner:
    def __init__(self, run_results):
        self._run_results = list(run_results)
        self.run_calls = []

    def run(self, agent_name, state, *, thread_id=None):
        self.run_calls.append((agent_name, state))
        return self._run_results.pop(0)

    def resume(self, agent_name, thread_id, *, updates=None):
        raise AssertionError("not used in this test")


def _tool_call(name, args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "c1", "type": "tool_call"}])


def test_observer_receives_node_tool_and_llm_events_during_a_real_run() -> None:
    llm = _ScriptedLLM([
        _tool_call("insights", {"query_entity": "fuel_trends"}),
        AIMessage(content=""),  # plan decides to stop
        AIMessage(content="Fuel costs are stable."),  # synthesize
    ])
    runner = _FakeRunner([RunResult(status="done", state={"query_result": [{"month": "2026-01"}]}, thread_id="t1")])
    observer = FleetLiveObserver(organization_id="org-1", user_id="user-1", role="admin")
    deps = OrchestratorDeps(llm=llm, runner=runner, observer=observer)

    session = OrchestratorSession(_token(), deps=deps)
    result = session.run("How are fuel costs trending?")

    assert result.status == "done"

    # UI channel: node + tool-start messages, in order, zero LLM calls used to produce them
    assert observer.ui_messages == [
        "Thinking and planning next steps...",  # plan, hop 1
        "Pulling strategic insights...",  # insights tool start
        "Thinking and planning next steps...",  # plan, hop 2 (decides to stop)
        "Drafting final response...",  # synthesize
    ]

    # Telemetry channel: 2 LLMTrace (plan hop 1 that made the tool call has
    # its own plan-LLM-call trace via record_llm in the plan node... actually
    # only hops that call the LLM produce an LLMTrace: plan(hop1), plan(hop2), synthesize = 3
    from orchestrator.audit_schemas import LLMTrace, ToolTrace

    llm_traces = [t for t in observer.traces if isinstance(t, LLMTrace)]
    tool_traces = [t for t in observer.traces if isinstance(t, ToolTrace)]

    assert len(llm_traces) == 3  # plan x2 + synthesize
    assert len(tool_traces) == 1
    assert tool_traces[0].agent_name == "insights"
    assert tool_traces[0].status == "done"

    # every trace from this turn shares the same trace_id
    assert len({t.trace_id for t in observer.traces}) == 1


def test_observer_records_hitl_pause_and_resume_under_the_same_trace_id() -> None:
    llm = _ScriptedLLM([
        _tool_call("assignment", {"assign_request": {
            "vehicle_plate": "ABC-123", "driver_name": "Jane", "assigned_at": "2026-01-01T08:00:00",
            "start_odometer": 1000, "take_condition": "good",
        }}),
        AIMessage(content=""),  # post-approval plan call: decides to stop
        AIMessage(content="Assigned ABC-123 to Jane."),  # synthesize
    ])
    runner = _FakeRunner([RunResult(status="awaiting_approval", state={}, thread_id="t1", pending_node="executing")])
    observer = FleetLiveObserver(organization_id="org-1", user_id="user-1", role="admin")
    deps = OrchestratorDeps(llm=llm, runner=runner, observer=observer)

    session = OrchestratorSession(_token(), deps=deps)
    paused = session.run("Assign ABC-123 to Jane.")

    assert paused.status == "awaiting_approval"
    assert observer.ui_messages[-1] == "Action paused: Waiting for your approval."

    from orchestrator.audit_schemas import ToolTrace

    pause_trace = next(t for t in observer.traces if isinstance(t, ToolTrace))
    assert pause_trace.status == "awaiting_approval"
    turn_trace_id = observer.trace_id

    # Resuming does NOT start a new turn (FR 4: one trace_id per session
    # turn, and an approval round-trip is part of the turn that paused).
    runner.resume = lambda agent_name, thread_id, *, updates=None: RunResult(
        status="done", state={"created_record": {"id": "a1"}}, thread_id=thread_id
    )
    resumed = session.approve()

    assert resumed.status == "done"
    assert observer.trace_id == turn_trace_id
    tool_traces = [t for t in observer.traces if isinstance(t, ToolTrace)]
    assert len(tool_traces) == 2
    assert tool_traces[1].status == "done"
    assert {t.trace_id for t in tool_traces} == {turn_trace_id}
