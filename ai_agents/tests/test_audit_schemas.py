import pytest
from pydantic import ValidationError

from orchestrator.audit_schemas import LLMTrace, ToolTrace


def test_llm_trace_defaults_timestamp() -> None:
    trace = LLMTrace(
        trace_id="t1", organization_id="org-1", user_id="u1", model_name="m",
        prompt_tokens=10, completion_tokens=5, latency_ms=100,
    )
    assert trace.timestamp is not None


def test_llm_trace_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        LLMTrace(
            trace_id="t1", organization_id="org-1", user_id="u1", model_name="m",
            prompt_tokens=10, completion_tokens=5, latency_ms=100, bogus=True,
        )


def test_tool_trace_status_must_be_one_of_four() -> None:
    with pytest.raises(ValidationError):
        ToolTrace(
            trace_id="t1", organization_id="org-1", user_id="u1", agent_name="fuel",
            attempt=1, input_payload={}, status="not-a-real-status", observation="", latency_ms=1,
        )


def test_tool_trace_accepts_all_four_statuses() -> None:
    for status in ["done", "halted", "awaiting_approval", "schema_error"]:
        trace = ToolTrace(
            trace_id="t1", organization_id="org-1", user_id="u1", agent_name="fuel",
            attempt=1, input_payload={}, status=status, observation="", latency_ms=1,
        )
        assert trace.status == status
