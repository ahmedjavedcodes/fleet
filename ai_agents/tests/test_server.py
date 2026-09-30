"""Tests for server.py's HTTP/SSE surface. OrchestratorSession itself is
injected as a fake (same convention as test_orchestrator_session.py) so
these run with no LLM call and no backend dependency -- they're testing the
HTTP wiring (auth, session lookup, SSE framing), not the orchestrator.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

import server
from orchestrator.session import TurnResult


def _token(role: str = "admin", sub: str = "user-1") -> str:
    payload = {"sub": sub, "org": "org-1", "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, "irrelevant-signing-key", algorithm="HS256")


def _auth(sub: str = "user-1") -> dict:
    return {"Authorization": f"Bearer {_token(sub=sub)}"}


class _FakeSession:
    """Scripted TurnResults, one per call, regardless of which method." queued
    in the order run/approve/modify/reject are expected to be invoked."""

    def __init__(self, token: str, **kwargs):
        self.token = token
        self.user_id = "user-1"  # the sub claim of _token()
        self.memory_session_id = kwargs.get("memory_session_id")
        self.results: list[TurnResult] = []

    def run(self, message: str):
        return self.results.pop(0)

    def approve(self):
        return self.results.pop(0)

    def modify(self, updates):
        return self.results.pop(0)

    def reject(self):
        return self.results.pop(0)


@pytest.fixture(autouse=True)
def _reset_sessions():
    server._SESSIONS.clear()
    server._SESSION_TOUCHED.clear()
    yield
    server._SESSIONS.clear()
    server._SESSION_TOUCHED.clear()


@pytest.fixture()
def client():
    return TestClient(server.app)


def _parse_sse(body: str) -> list[dict]:
    # sse-starlette sends CRLF line endings, not LF (this bit the frontend's
    # own SSE parser identically -- see lib/api/sse.ts in `frontend`).
    frames = []
    for block in body.replace("\r\n", "\n").strip().split("\n\n"):
        if not block.strip():
            continue
        event = None
        data = None
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = line[len("data:") :].strip()
        if data is not None:
            frames.append({"event": event, "data": data})
    return frames


def test_create_session_requires_a_bearer_token(client):
    resp = client.post("/api/v1/chat/sessions")
    assert resp.status_code == 401


def test_create_session_rejects_a_malformed_token(client):
    resp = client.post("/api/v1/chat/sessions", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


def test_create_session_succeeds_with_a_valid_token(client, monkeypatch):
    monkeypatch.setattr(server, "OrchestratorSession", _FakeSession)
    resp = client.post("/api/v1/chat/sessions", headers={"Authorization": f"Bearer {_token()}"})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]
    assert session_id in server._SESSIONS


def test_unknown_session_id_404s(client):
    resp = client.post("/api/v1/chat/sessions/does-not-exist/messages", json={"message": "hi"}, headers=_auth())
    assert resp.status_code == 404


def test_send_message_streams_activity_token_and_done_events(client, monkeypatch):
    monkeypatch.setattr(server, "OrchestratorSession", _FakeSession)
    resp = client.post("/api/v1/chat/sessions", headers={"Authorization": f"Bearer {_token()}"})
    session_id = resp.json()["session_id"]
    server._SESSIONS[session_id].results.append(
        TurnResult(status="done", final_response="Hello there", hitl_state=None, state={})
    )

    resp = client.post(f"/api/v1/chat/sessions/{session_id}/messages", json={"message": "hi"}, headers=_auth())
    assert resp.status_code == 200
    frames = _parse_sse(resp.text)

    assert frames[0]["event"] == "activity"
    assert frames[-1] == {"event": "done", "data": '{"status": "done"}'}
    token_frames = [f for f in frames if f["event"] == "token"]
    assert "".join(__import__("json").loads(f["data"])["text"] for f in token_frames) == "Hello there"


def test_awaiting_approval_streams_hitl_state_instead_of_tokens(client, monkeypatch):
    monkeypatch.setattr(server, "OrchestratorSession", _FakeSession)
    resp = client.post("/api/v1/chat/sessions", headers={"Authorization": f"Bearer {_token()}"})
    session_id = resp.json()["session_id"]
    hitl_state = {"agent_name": "assignment", "thread_id": "t1", "approval_prompt": "Assign this driver?"}
    server._SESSIONS[session_id].results.append(
        TurnResult(status="awaiting_approval", final_response=None, hitl_state=hitl_state, state={})
    )

    resp = client.post(f"/api/v1/chat/sessions/{session_id}/messages", json={"message": "assign a driver"}, headers=_auth())
    frames = _parse_sse(resp.text)
    approval_frames = [f for f in frames if f["event"] == "approval_required"]
    assert len(approval_frames) == 1
    assert __import__("json").loads(approval_frames[0]["data"])["hitl_state"] == hitl_state
    assert not any(f["event"] == "token" for f in frames)


def test_a_session_exception_streams_an_error_event_not_a_500(client, monkeypatch):
    class _ExplodingSession(_FakeSession):
        def run(self, message: str):
            raise RuntimeError("boom")

    monkeypatch.setattr(server, "OrchestratorSession", _ExplodingSession)
    resp = client.post("/api/v1/chat/sessions", headers={"Authorization": f"Bearer {_token()}"})
    session_id = resp.json()["session_id"]

    resp = client.post(f"/api/v1/chat/sessions/{session_id}/messages", json={"message": "hi"}, headers=_auth())
    assert resp.status_code == 200
    frames = _parse_sse(resp.text)
    assert frames[-1]["event"] == "error"


def test_approve_endpoint_calls_session_approve(client, monkeypatch):
    monkeypatch.setattr(server, "OrchestratorSession", _FakeSession)
    resp = client.post("/api/v1/chat/sessions", headers={"Authorization": f"Bearer {_token()}"})
    session_id = resp.json()["session_id"]
    server._SESSIONS[session_id].results.append(TurnResult(status="done", final_response="Done.", hitl_state=None, state={}))

    resp = client.post(f"/api/v1/chat/sessions/{session_id}/approve", headers=_auth())
    assert resp.status_code == 200
    assert "Done." in resp.text
