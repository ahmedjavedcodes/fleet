"""Tests for FleetLiveObserver. Each test is named after the Acceptance
Criterion it covers in ai_agents/specs/fleet-live-observer.md, plus a few
covering the sync-vs-async dispatch design documented in callbacks.py's
module docstring (graph.py never triggers on_tool_start/on_tool_end
automatically -- it calls the sync recording API directly).
"""

import asyncio

import pytest

from orchestrator.callbacks import FleetLiveObserver
from orchestrator.audit_schemas import LLMTrace, ToolTrace


def _observer(**overrides) -> FleetLiveObserver:
    defaults = dict(organization_id="org-1", user_id="user-1", role="admin")
    return FleetLiveObserver(**{**defaults, **overrides})


def test_ac1_sensitive_input_payload_redacted_before_trace_built() -> None:
    observer = _observer()
    observer.record_tool_result(
        "c1", "foundation", {"license_number": "DL1234", "vehicle_plate": "ABC-123"},
        attempt=1, status="done", observation_text="ok",
    )
    trace = observer.traces[-1]
    assert isinstance(trace, ToolTrace)
    assert trace.input_payload["license_number"] == "[REDACTED]"
    assert trace.input_payload["vehicle_plate"] == "ABC-123"


def test_ac1_image_bytes_in_raw_result_redacted() -> None:
    observer = _observer()
    observer.record_tool_result(
        "c1", "foundation", {}, attempt=1, status="done", observation_text="ok",
        raw_result={"extracted": {"image_bytes": b"binary-data", "make": "Toyota"}},
    )
    trace = observer.traces[-1]
    assert "[REDACTED]" in trace.observation
    assert b"binary-data" not in trace.observation.encode()


def test_ac2_interpolation_exception_does_not_raise() -> None:
    observer = _observer()
    # a non-dict args value would break naive dict.get() calls inside
    # interpolate_tool_start -- the observer must swallow this, not crash
    # the caller (graph.py's execute_tool).
    message = observer.start_tool_call("c1", "assignment", args="not-a-dict")  # type: ignore[arg-type]
    assert isinstance(message, str)  # fell back to a generic message, no exception


def test_ac2_sink_failure_does_not_raise(caplog: pytest.LogCaptureFixture) -> None:
    async def failing_sink(trace):
        raise RuntimeError("db connection timeout")

    observer = _observer(sink=failing_sink)

    async def _run():
        queue = asyncio.Queue()
        observer.attach_queue(queue)
        observer.record_llm(model_name="m", prompt_tokens=1, completion_tokens=1, latency_ms=5)
        worker = asyncio.create_task(observer.run_worker(queue))
        await queue.join()
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker

    asyncio.run(_run())  # must not raise despite the sink always failing


def test_ac2_malformed_trace_data_does_not_raise() -> None:
    observer = _observer()
    # attempt/latency are int fields -- passing something un-coercible must
    # be swallowed, not propagate into the ReAct loop.
    observer.record_tool_result(
        "c1", "foundation", {}, attempt="not-an-int", status="done", observation_text="ok",  # type: ignore[arg-type]
    )
    assert observer.traces == []  # failed to build; nothing was recorded, nothing raised


def test_ac3_schema_error_trace_then_corrected_done_trace_share_trace_id() -> None:
    observer = _observer()
    observer.record_tool_result(
        "c1", "assignment", {"bogus": True}, attempt=1, status="schema_error",
        observation_text="Invalid arguments for this tool.",
    )
    observer.record_tool_result(
        "c1", "assignment", {"assign_request": {}}, attempt=2, status="done", observation_text="assignment succeeded",
    )

    schema_error_trace, done_trace = observer.traces
    assert schema_error_trace.status == "schema_error"
    assert schema_error_trace.attempt == 1
    assert done_trace.status == "done"
    assert done_trace.attempt == 2
    assert schema_error_trace.trace_id == done_trace.trace_id


def test_ac4_tool_start_pushes_ui_string_without_llm_call() -> None:
    observer = _observer()
    message = observer.start_tool_call("c1", "maintenance", {"query_entity": "low_stock"})
    assert message == "Verifying maintenance inventory for low_stock..."
    assert observer.ui_messages == [message]


def test_ac4_node_and_hitl_pause_messages_reach_ui_sink() -> None:
    received = []
    observer = _observer(ui_sink=received.append)

    observer.record_node("plan")
    observer.start_tool_call("c1", "insights", {"query_entity": "fuel_trends"})
    observer.record_hitl_pause()

    assert received == [
        "Thinking and planning next steps...",
        "Pulling strategic insights...",
        "Action paused: Waiting for your approval.",
    ]


def test_start_turn_resets_trace_id_and_ui_messages() -> None:
    observer = _observer()
    observer.record_node("plan")
    first_trace_id = observer.trace_id

    new_trace_id = observer.start_turn()

    assert new_trace_id != first_trace_id
    assert observer.trace_id == new_trace_id
    assert observer.ui_messages == []


def test_record_llm_builds_valid_llm_trace() -> None:
    observer = _observer()
    observer.record_llm(model_name="openai/gpt-oss-20b", prompt_tokens=120, completion_tokens=30, latency_ms=450)

    trace = observer.traces[-1]
    assert isinstance(trace, LLMTrace)
    assert trace.organization_id == "org-1"
    assert trace.model_name == "openai/gpt-oss-20b"
    assert trace.prompt_tokens == 120


def test_run_worker_drains_queue_via_sink() -> None:
    received = []

    async def sink(trace):
        received.append(trace)

    observer = _observer(sink=sink)

    async def _run():
        queue = asyncio.Queue()
        observer.attach_queue(queue)
        observer.record_llm(model_name="m", prompt_tokens=1, completion_tokens=2, latency_ms=3)
        observer.record_tool_result("c1", "insights", {}, attempt=1, status="done", observation_text="ok")

        worker = asyncio.create_task(observer.run_worker(queue))
        await queue.join()
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker

    asyncio.run(_run())
    assert len(received) == 2


def test_activity_sink_receives_each_step_attributed_to_its_agent() -> None:
    received: list[tuple[str, str]] = []
    observer = _observer(activity_sink=lambda agent, text: received.append((agent, text)))

    observer.record_node("plan")
    observer.start_tool_call("c1", "fuel", {"trip_fields": {"vehicle_id": "v1"}})
    observer.record_hitl_pause()

    assert received == [
        ("orchestrator", "Thinking and planning next steps..."),
        ("fuel", "Logging the trip..."),
        ("orchestrator", "Action paused: Waiting for your approval."),
    ]


def test_a_failing_activity_sink_never_breaks_the_turn() -> None:
    def boom(agent, text):
        raise RuntimeError("client went away")

    observer = _observer(activity_sink=boom)
    assert observer.record_node("plan") == "Thinking and planning next steps..."
