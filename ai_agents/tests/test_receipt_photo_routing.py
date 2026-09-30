"""A receipt photo must reach the vision model when the user asks to log a fuel fill, even if the planning model forgets
to set document_type="receipt" (DeepSeek, the paid fallback tier, often does)."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from langchain_core.messages import AIMessage

from orchestrator.graph import OrchestratorDeps
from orchestrator.runner import RunResult
from orchestrator.session import OrchestratorSession


def _token() -> str:
    payload = {"sub": "user-1", "org": "org-1", "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, "irrelevant-signing-key", algorithm="HS256")


class _LLM:
    def __init__(self, *responses):
        self._responses = list(responses)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages, **kwargs):
        return self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]


class _Runner:
    def __init__(self):
        self.calls = []

    def run(self, agent_name, state, *, thread_id=None):
        self.calls.append((agent_name, state))
        return RunResult(status="done", state={"query_result": []}, thread_id="t")


def _call(name, args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "c1", "type": "tool_call"}])


def _run(tool_call, *, photo=True):
    runner = _Runner()
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=_LLM(tool_call, AIMessage(content=""), AIMessage(content="Done.")), runner=runner))
    kwargs = {"image_bytes": b"jpeg-bytes", "mime_type": "image/jpeg"} if photo else {}
    session.run("Log this fuel fill for AB-1234, the total was 50 liters at Rs 280 per liter.", **kwargs)
    return runner.calls


FUEL_FIELDS = {"vehicle_id": "v1", "liters_filled": 50, "price_per_liter": 280}


def test_a_fuel_log_with_a_photo_attached_is_sent_to_the_vision_model_without_the_model_asking() -> None:
    (agent, state), = _run(_call("fuel", {"fuel_fields": FUEL_FIELDS}))

    assert agent == "fuel"
    assert state["document_type"] == "receipt"
    assert state["image_bytes"] == b"jpeg-bytes" and state["mime_type"] == "image/jpeg"


def test_when_the_model_does_set_the_document_type_nothing_changes() -> None:
    (_, state), = _run(_call("fuel", {"document_type": "receipt", "fuel_fields": FUEL_FIELDS}))

    assert state["document_type"] == "receipt" and state["image_bytes"] == b"jpeg-bytes"


@pytest.mark.parametrize(
    "arguments",
    [
        {"query_entity": "fuel_logs"},  # a read is not about the photo
        {"query_entity": "fuel_summary", "query_days": 30},
        {"trip_fields": {"driver_id": "d1", "vehicle_id": "v1", "start_time": "2026-09-01T08:00:00", "end_time": "2026-09-01T09:00:00", "start_odometer": 1, "end_odometer": 2}},
    ],
    ids=["read", "summary", "trip"],
)
def test_reads_and_trips_never_take_the_photo(arguments) -> None:
    (_, state), = _run(_call("fuel", arguments))

    assert "document_type" not in state and "image_bytes" not in state


def test_without_a_photo_a_text_only_fuel_log_is_left_alone() -> None:
    (_, state), = _run(_call("fuel", {"fuel_fields": FUEL_FIELDS}), photo=False)

    assert "document_type" not in state and "image_bytes" not in state


def test_other_agents_are_not_given_a_guessed_document_type() -> None:
    """foundation reads licenses, registration cards and supplier documents: which one is the model's call to make."""
    (_, state), = _run(_call("foundation", {"query_entity": "vehicles"}))

    assert "document_type" not in state
