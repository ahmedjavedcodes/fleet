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


# --- the full hook set, and the live activity feed ------------------------------------


def test_every_session_is_built_with_the_full_hook_set(monkeypatch):
    from orchestrator.cache import ExecutionCache
    from orchestrator.callbacks import FleetLiveObserver
    from orchestrator.webhooks import AlertDispatcher

    built = {}

    class _Capture(_FakeSession):
        def __init__(self, token, **kwargs):
            super().__init__(token, **kwargs)
            built["deps"] = kwargs["deps"]

    monkeypatch.setattr(server, "OrchestratorSession", _Capture)
    monkeypatch.setattr(server, "_fact_checker_llm", lambda: "checker")
    monkeypatch.setattr(server, "_shared_memory", lambda: "memory")
    server._open_session(_token(sub="user-9"))

    deps = built["deps"]
    assert deps.memory == "memory"
    assert deps.fact_checker_llm == "checker"
    assert isinstance(deps.cache, ExecutionCache) and deps.cache is server._EXECUTION_CACHE
    assert isinstance(deps.webhooks, AlertDispatcher)
    assert isinstance(deps.observer, FleetLiveObserver)
    assert (deps.observer.user_id, deps.observer.organization_id, deps.observer.role) == ("user-9", "org-1", "admin")


def test_observer_steps_stream_live_as_activity_events(client, monkeypatch):
    import json

    from orchestrator.callbacks import FleetLiveObserver

    class _ObservedSession(_FakeSession):
        def __init__(self, token, **kwargs):
            super().__init__(token, **kwargs)
            self.deps = type("Deps", (), {"observer": FleetLiveObserver(organization_id="org-1", user_id="user-1", role="admin")})()

        def run(self, message):
            observer = self.deps.observer
            observer.record_node("plan")
            observer.start_tool_call("c1", "fuel", {"trip_fields": {"vehicle_id": "v1"}})
            observer.start_tool_call("c2", "made_up_tool", {})
            observer.record_node("synthesize")
            return TurnResult(status="done", final_response="Logged.", hitl_state=None, state={})

    monkeypatch.setattr(server, "OrchestratorSession", _ObservedSession)
    session_id = client.post("/api/v1/chat/sessions", headers=_auth()).json()["session_id"]
    resp = client.post(f"/api/v1/chat/sessions/{session_id}/messages", json={"message": "log a trip"}, headers=_auth())

    activity = [json.loads(f["data"]) for f in _parse_sse(resp.text) if f["event"] == "activity"]
    assert [(a["agent"], a["step"], a["done"]) for a in activity] == [
        ("orchestrator", "Reading your message…", False),
        ("orchestrator", "Reading your message…", True),
        ("orchestrator", "Thinking and planning next steps...", False),
        ("orchestrator", "Thinking and planning next steps...", True),
        ("fuel", "Logging the trip...", False),
        ("fuel", "Logging the trip...", True),
        ("orchestrator", "Working on it...", False),  # unknown tool name: never an agent key the UI can't parse
        ("orchestrator", "Working on it...", True),
        ("orchestrator", "Drafting final response...", False),
        ("orchestrator", "Drafting final response...", True),
    ]
    assert server._SESSIONS[session_id].deps.observer.activity_sink is None  # detached after the turn


def test_sessions_get_document_search_and_rag_sampling(monkeypatch):
    from mcp_server.document_tools import BackendDocumentRetriever
    from orchestrator.rag_eval import RagTriadEvaluator
    from orchestrator.tools import build_llm_tools

    built = {}

    class _Capture(_FakeSession):
        def __init__(self, token, **kwargs):
            super().__init__(token, **kwargs)
            built["deps"] = kwargs["deps"]

    monkeypatch.setattr(server, "OrchestratorSession", _Capture)
    monkeypatch.setattr(server, "_fact_checker_llm", lambda: None)
    monkeypatch.setattr(server, "_shared_memory", lambda: None)
    server._open_session(_token())

    deps = built["deps"]
    assert isinstance(deps.documents, BackendDocumentRetriever)
    assert isinstance(deps.rag_evaluator, RagTriadEvaluator)
    # What the plan node binds for this session: the six sub-agents plus search_documents.
    names = [t.name for t in build_llm_tools(include_memory=deps.memory is not None, include_documents=deps.documents is not None)]
    assert "search_documents" in names and len(names) == 7
