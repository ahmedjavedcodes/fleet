"""Proves all three execution-post_hooks.md hooks are actually wired into a
real OrchestratorSession/graph run, not just unit-tested in isolation --
same pattern as test_orchestrator_prehooks_integration.py.
"""

from datetime import datetime, timedelta, timezone

import jwt
from langchain_core.messages import AIMessage

from orchestrator.cache import ExecutionCache
from orchestrator.graph import OrchestratorDeps
from orchestrator.runner import RunResult
from orchestrator.session import OrchestratorSession
from orchestrator.webhooks import AlertDispatcher


def _token(role: str = "admin") -> str:
    payload = {"sub": "user-1", "org": "org-1", "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, "irrelevant-signing-key", algorithm="HS256")


class _ScriptedLLM:
    def __init__(self, responses):
        self._responses = list(responses)
        self.invoke_calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.invoke_calls += 1
        return self._responses.pop(0)


class _ScriptedFactChecker:
    """A minimal stand-in for the secondary Groq LLM check_response_against_
    scratchpad calls -- only needs .invoke(messages).content, no tool-binding."""

    def __init__(self, verdicts):
        self._verdicts = list(verdicts)
        self.invoke_calls = 0

    def invoke(self, messages):
        self.invoke_calls += 1

        class _Response:
            content = self._verdicts.pop(0)

        return _Response()


class _FakeRunner:
    def __init__(self, run_results):
        self._run_results = list(run_results)
        self.run_calls = []

    def run(self, agent_name, state, *, thread_id=None):
        self.run_calls.append((agent_name, state))
        return self._run_results.pop(0)

    def resume(self, agent_name, thread_id, *, updates=None):
        raise AssertionError("not used in this test")


def _tool_call(name, args, call_id="c1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def test_ac1_write_invalidates_cached_reads_for_own_and_insights_namespace() -> None:
    llm = _ScriptedLLM([
        # Turn 1: dashboard read -> gets cached
        _tool_call("insights", {"query_entity": "dashboard_summary"}),
        AIMessage(content=""),
        AIMessage(content="10 vehicles."),
        # Turn 2: assignment write -> must invalidate the insights namespace too
        _tool_call("assignment", {"assign_request": {
            "vehicle_plate": "XYZ-999", "driver_name": "Jane", "assigned_at": "2026-01-01T08:00:00",
            "start_odometer": 1000, "take_condition": "good",
        }}),
        AIMessage(content=""),
        AIMessage(content="Assigned."),
        # Turn 3: dashboard read again -> must NOT be served from the stale cache
        _tool_call("insights", {"query_entity": "dashboard_summary"}),
        AIMessage(content=""),
        AIMessage(content="11 vehicles."),
    ])
    runner = _FakeRunner([
        RunResult(status="done", state={"query_result": {"total_vehicles": 10}}, thread_id="t1"),
        RunResult(status="done", state={"created_record": {"id": "a1"}}, thread_id="t2"),
        RunResult(status="done", state={"query_result": {"total_vehicles": 11}}, thread_id="t3"),
    ])
    cache = ExecutionCache()
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner, cache=cache))

    session.run("Give me the dashboard summary.")
    session.run("Assign vehicle XYZ-999 to Jane.")
    third = session.run("Give me the dashboard summary.")

    assert third.status == "done"
    # all three agent calls actually reached the sub-agent runner -- the
    # third dashboard read was NOT served from the (now-invalidated) cache.
    assert len(runner.run_calls) == 3
    assert "total_vehicles\":11" in third.state["scratchpad"][0]["observation"]


def test_read_only_calls_never_trigger_invalidation() -> None:
    # A read must never purge its own or anyone else's cache -- only a
    # successful WRITE does (execute_tool's `not is_read_only` guard).
    llm = _ScriptedLLM([
        _tool_call("insights", {"query_entity": "dashboard_summary"}),
        AIMessage(content=""),
        AIMessage(content="10 vehicles."),
        _tool_call("insights", {"query_entity": "dashboard_summary"}),
        AIMessage(content=""),
        AIMessage(content="10 vehicles again."),
    ])
    runner = _FakeRunner([RunResult(status="done", state={"query_result": {"total_vehicles": 10}}, thread_id="t1")])
    cache = ExecutionCache()
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner, cache=cache))

    session.run("Give me the dashboard summary.")
    session.run("Give me the dashboard summary.")

    assert len(runner.run_calls) == 1  # second read was a cache hit, not invalidated by the first


def test_ac2_critical_incident_write_drops_alert_into_queue() -> None:
    llm = _ScriptedLLM([
        _tool_call("accountability", {"document_text": "Severe collision on Route 9."}),
        AIMessage(content=""),
        AIMessage(content="Incident logged."),
    ])
    runner = _FakeRunner([RunResult(status="done", state={"created_record": {"id": "i1", "severity": "critical"}}, thread_id="t1")])
    webhooks = AlertDispatcher()
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner, webhooks=webhooks))

    result = session.run("Log this incident: severe collision on Route 9.")

    assert result.status == "done"
    assert len(webhooks.alerts) == 1
    assert webhooks.alerts[0].rule == "critical_incident"
    assert webhooks.alerts[0].organization_id == "org-1"
    assert webhooks.alerts[0].agent_name == "accountability"


def test_minor_incident_does_not_fire_an_alert() -> None:
    llm = _ScriptedLLM([
        _tool_call("accountability", {"document_text": "Minor scrape in the parking lot."}),
        AIMessage(content=""),
        AIMessage(content="Incident logged."),
    ])
    runner = _FakeRunner([RunResult(status="done", state={"created_record": {"id": "i2", "severity": "minor"}}, thread_id="t1")])
    webhooks = AlertDispatcher()
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner, webhooks=webhooks))

    session.run("Log this incident: minor scrape in the parking lot.")

    assert webhooks.alerts == []


def test_no_webhooks_configured_does_not_change_behavior() -> None:
    # AlertDispatcher defaults to None on OrchestratorDeps -- a write must
    # still complete normally with no alert evaluation attempted at all.
    llm = _ScriptedLLM([
        _tool_call("accountability", {"document_text": "Severe collision on Route 9."}),
        AIMessage(content=""),
        AIMessage(content="Incident logged."),
    ])
    runner = _FakeRunner([RunResult(status="done", state={"created_record": {"id": "i1", "severity": "critical"}}, thread_id="t1")])
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner))

    result = session.run("Log this incident: severe collision on Route 9.")

    assert result.status == "done"


def test_ac3_hallucinated_number_forces_a_synthesize_rewrite() -> None:
    llm = _ScriptedLLM([
        _tool_call("maintenance", {"document_text": "Replaced ABC-123 brake pads, cost $50."}),  # a write: fact-checked
        AIMessage(content=""),
        AIMessage(content="Repair cost $500."),  # hallucinated -- scratchpad says $50
        AIMessage(content="Repair cost $50."),  # corrected on the forced rewrite
    ])
    runner = _FakeRunner([RunResult(status="done", state={"query_result": {"repair_cost": "$50"}}, thread_id="t1")])
    fact_checker = _ScriptedFactChecker(["YES", "NO"])
    session = OrchestratorSession(
        _token(), deps=OrchestratorDeps(llm=llm, runner=runner, fact_checker_llm=fact_checker)
    )

    result = session.run("What did the last repair cost?")

    assert result.status == "done"
    assert result.final_response == "Repair cost $50."
    assert fact_checker.invoke_calls == 2  # flagged once, then confirmed clean


def test_no_fact_checker_configured_skips_the_check_entirely() -> None:
    # fact_checker_llm defaults to None on OrchestratorDeps -- the fact_check
    # node must be a pure pass-through, matching every pre-existing test.
    llm = _ScriptedLLM([
        _tool_call("maintenance", {"query_entity": "maintenance_logs"}),
        AIMessage(content=""),
        AIMessage(content="Repair cost $500."),
    ])
    runner = _FakeRunner([RunResult(status="done", state={"query_result": {"repair_cost": "$50"}}, thread_id="t1")])
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner))

    result = session.run("What did the last repair cost?")

    assert result.status == "done"
    assert result.final_response == "Repair cost $500."  # never rewritten -- no checker configured


def test_fact_check_retries_are_bounded_and_still_return_a_response() -> None:
    # Even if the checker flags every draft, MAX_FACT_CHECK_RETRIES caps the
    # loop -- the user always gets a final_response, never an infinite loop.
    llm = _ScriptedLLM([
        _tool_call("maintenance", {"document_text": "Replaced ABC-123 brake pads, cost $50."}),  # a write: fact-checked
        AIMessage(content=""),
        AIMessage(content="draft 1"),
        AIMessage(content="draft 2"),
        AIMessage(content="draft 3"),
    ])
    runner = _FakeRunner([RunResult(status="done", state={"query_result": {"repair_cost": "$50"}}, thread_id="t1")])
    fact_checker = _ScriptedFactChecker(["YES", "YES", "YES"])
    session = OrchestratorSession(
        _token(), deps=OrchestratorDeps(llm=llm, runner=runner, fact_checker_llm=fact_checker)
    )

    result = session.run("What did the last repair cost?")

    assert result.status == "done"
    assert result.final_response == "draft 3"  # 1 initial + MAX_FACT_CHECK_RETRIES(2) rewrites, then forced to stop


def test_fact_check_skips_a_turn_where_no_tool_ran() -> None:
    llm = _ScriptedLLM([AIMessage(content=""), AIMessage(content="Hi Jane, I can help with fleet questions.")])
    fact_checker = _ScriptedFactChecker(["YES"])  # would force a rewrite if it were asked
    session = OrchestratorSession(
        _token(), deps=OrchestratorDeps(llm=llm, runner=_FakeRunner([]), fact_checker_llm=fact_checker)
    )

    result = session.run("Hello, what can you do for my fleet?")

    assert result.final_response == "Hi Jane, I can help with fleet questions."
    assert fact_checker.invoke_calls == 0


def test_fact_check_treats_recalled_memory_as_grounding() -> None:
    llm = _ScriptedLLM([
        _tool_call("maintenance", {"document_text": "Replaced ABC-123 brake pads, cost $50."}),  # a write: fact-checked
        AIMessage(content=""),
        AIMessage(content="Repair cost $50, shown in PKR as you prefer."),
    ])
    runner = _FakeRunner([RunResult(status="done", state={"query_result": {"repair_cost": "$50"}}, thread_id="t1")])
    seen: list[str] = []

    class _RecordingChecker:
        def invoke(self, messages):
            seen.append(messages[-1].content)

            class _R:
                content = "NO"

            return _R()

    class _Memory:
        fetch_timeout_s = 1.0

        def start_session(self, context):
            return "s1"

        def record_message(self, *a, **k):
            return None

        def fetch_context(self, context, session_id, query):
            return "Remembered facts:\n- [personal] Prefers amounts in PKR"

        def on_write(self, *a, **k):
            return None

    session = OrchestratorSession(
        _token(), deps=OrchestratorDeps(llm=llm, runner=runner, fact_checker_llm=_RecordingChecker(), memory=_Memory())
    )

    session.run("Log the brake repair for ABC-123 at $50 in my usual currency.")

    assert "[maintenance]" in seen[0]
    assert "[memory]" in seen[0] and "Prefers amounts in PKR" in seen[0]


def test_cached_reads_are_scoped_to_the_user_through_the_graph() -> None:
    from orchestrator.cache import ExecutionCache

    cache = ExecutionCache()

    def run_as(sub: str):
        llm = _ScriptedLLM([_tool_call("insights", {"query_entity": "dashboard_summary"}), AIMessage(content=""), AIMessage(content="ok")])
        runner = _FakeRunner([RunResult(status="done", state={"query_result": {"total_vehicles": 10}}, thread_id="t1")])
        token = jwt.encode(
            {"sub": sub, "org": "org-1", "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(minutes=30)},
            "irrelevant-signing-key", algorithm="HS256",
        )
        OrchestratorSession(token, deps=OrchestratorDeps(llm=llm, runner=runner, cache=cache)).run("Show the dashboard summary")
        return runner

    assert len(run_as("user-a").run_calls) == 1
    assert len(run_as("user-a").run_calls) == 0  # same user: served from cache
    assert len(run_as("user-b").run_calls) == 1  # same org, different user: never served user-a's read


# --- truth-checker only for writes or multi-hop turns --------------------------------


def test_a_single_read_skips_the_fact_checker_entirely() -> None:
    llm = _ScriptedLLM([
        _tool_call("maintenance", {"query_entity": "maintenance_logs"}),
        AIMessage(content=""),
        AIMessage(content="Repair cost $500."),
    ])
    runner = _FakeRunner([RunResult(status="done", state={"query_result": {"repair_cost": "$50"}}, thread_id="t1")])
    fact_checker = _ScriptedFactChecker(["YES"])
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner, fact_checker_llm=fact_checker))

    result = session.run("What did the last repair cost?")

    assert fact_checker.invoke_calls == 0  # no extra LLM round-trip for a plain read
    assert result.final_response == "Repair cost $500."


def test_a_multi_hop_read_is_fact_checked() -> None:
    llm = _ScriptedLLM([
        _tool_call("foundation", {"query_entity": "vehicles"}, call_id="c1"),
        _tool_call("maintenance", {"query_entity": "maintenance_logs"}, call_id="c2"),
        AIMessage(content=""),
        AIMessage(content="ABC-123's last repair cost $50."),
    ])
    runner = _FakeRunner([
        RunResult(status="done", state={"query_result": [{"id": "v1", "plate_number": "ABC-123"}]}, thread_id="t1"),
        RunResult(status="done", state={"query_result": {"repair_cost": "$50"}}, thread_id="t2"),
    ])
    fact_checker = _ScriptedFactChecker(["NO"])
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner, fact_checker_llm=fact_checker))

    session.run("What did ABC-123's last repair cost?")

    assert fact_checker.invoke_calls == 1


def test_a_write_is_fact_checked_even_as_a_single_hop() -> None:
    llm = _ScriptedLLM([
        _tool_call("maintenance", {"document_text": "Replaced ABC-123 brake pads, $50."}),
        AIMessage(content=""),
        AIMessage(content="Logged the brake service."),
    ])
    runner = _FakeRunner([RunResult(status="done", state={"created_record": {"id": "m1"}}, thread_id="t1")])
    fact_checker = _ScriptedFactChecker(["NO"])
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner, fact_checker_llm=fact_checker))

    session.run("Log a brake service for ABC-123, $50.")

    assert fact_checker.invoke_calls == 1
