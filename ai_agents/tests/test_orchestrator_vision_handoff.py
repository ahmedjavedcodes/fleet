"""An image attached to a chat turn reaches the planner (as a note) and the
vision sub-agent the planner routes it to (as bytes), and the stored upload's
URL rides along to an incident filed from it."""

from datetime import datetime, timedelta, timezone

import jwt
from langchain_core.messages import AIMessage

from orchestrator.graph import OrchestratorDeps
from orchestrator.runner import RunResult
from orchestrator.session import OrchestratorSession

URL = "/uploads/incidents/0b7c7a58-7f0e-4d5a-9a57-6f1f2c3d4e5f.jpg"


def _token() -> str:
    payload = {"sub": "user-1", "org": "org-1", "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, "irrelevant-signing-key", algorithm="HS256")


class _LLM:
    def __init__(self, responses):
        self.responses, self.seen = list(responses), []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.seen.append(messages)
        return self.responses.pop(0)


class _Runner:
    def __init__(self):
        self.calls = []

    def run(self, agent_name, state, *, thread_id=None):
        self.calls.append((agent_name, state))
        return RunResult(status="done", state={"created_record": {"id": "x"}}, thread_id="t1")

    def resume(self, *a, **k):
        raise AssertionError


def _call(name, args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "c1", "type": "tool_call"}])


def _run(tool_call, message="Please file this", **attachment):
    llm = _LLM([tool_call, AIMessage(content=""), AIMessage(content="Done.")])
    runner = _Runner()
    OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner)).run(message, **attachment)
    return llm, runner


def _text(messages) -> str:
    return "\n".join(str(m.content) for m in messages)


def test_the_planner_is_told_a_photo_is_attached_and_how_to_route_it() -> None:
    llm, _ = _run(_call("fuel", {"document_type": "receipt"}), image_bytes=b"\xff\xd8", mime_type="image/jpeg")
    planning = _text(llm.seen[0])
    assert "A photo is attached" in planning and "receipt" in planning and "incident_report" in planning

    without, _ = _run(_call("fuel", {"query_entity": "fuel_logs"}), message="Show fuel logs")
    assert "A photo is attached" not in _text(without.seen[0])


def test_image_and_its_url_reach_the_incident_agent() -> None:
    _, runner = _run(
        _call("accountability", {"document_type": "incident_report", "severity": "moderate"}),
        image_bytes=b"\xff\xd8", mime_type="image/jpeg", attachment_url=URL,
    )
    agent, state = runner.calls[0]
    assert agent == "accountability"
    assert state["image_bytes"] == b"\xff\xd8" and state["mime_type"] == "image/jpeg"
    assert state["attachment_url"] == URL


def test_other_vision_agents_get_the_image_but_no_attachment_url() -> None:
    _, runner = _run(_call("fuel", {"document_type": "receipt"}), image_bytes=b"\x89PNG", mime_type="image/png", attachment_url=URL)
    _, state = runner.calls[0]
    assert state["image_bytes"] == b"\x89PNG"
    assert "attachment_url" not in state  # FuelAgentState has no such field


def test_a_read_call_never_receives_the_image() -> None:
    _, runner = _run(_call("fuel", {"query_entity": "fuel_logs"}), image_bytes=b"\xff\xd8", mime_type="image/jpeg")
    assert "image_bytes" not in runner.calls[0][1]
