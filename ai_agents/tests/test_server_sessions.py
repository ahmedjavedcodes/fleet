"""Chat session management on server.py: identity, ownership, resume-after-restart, and the
sidebar endpoints (list / transcript / rename).

Like test_server.py, OrchestratorSession and the backend memory calls are injected as fakes, so
these test the HTTP wiring and the guarantees around it, not the orchestrator.
"""

import json
import types
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

import server
from orchestrator.session import TurnResult
from tools.api_client import BackendAPIError

SESSION_ID = "8f6c1d7e-3b0a-4a51-9d6e-0a1b2c3d4e5f"


def _auth(sub: str = "user-1") -> dict:
    payload = {"sub": sub, "org": "org-1", "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return {"Authorization": f"Bearer {jwt.encode(payload, 'irrelevant-signing-key', algorithm='HS256')}"}


class _FakeSession:
    def __init__(self, token: str, **kwargs):
        self.token = token
        self.user_id = "user-1"
        self.memory_session_id = kwargs.get("memory_session_id")
        self.kwargs = kwargs
        self.results: list[TurnResult] = []

    def run(self, message: str):
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


def _memory(monkeypatch, **fns):
    """Swap the backend memory calls for scripted fakes; anything unscripted fails loudly."""

    def _missing(name):
        def call(*args, **kwargs):
            raise AssertionError(f"unexpected backend call: {name}")

        return call

    names = ["get_session_context_tool", "list_sessions_tool", "get_session_messages_tool", "rename_session_tool"]
    monkeypatch.setattr(server, "memory_tools", types.SimpleNamespace(**{n: fns.get(n, _missing(n)) for n in names}))


def _done(text: str) -> TurnResult:
    return TurnResult(status="done", final_response=text, hitl_state=None, state={})


# --- Identity and ownership ---------------------------------------------------------------


def test_message_endpoints_require_a_bearer_token(client, monkeypatch):
    monkeypatch.setattr(server, "OrchestratorSession", _FakeSession)
    session_id = client.post("/api/v1/chat/sessions", headers=_auth()).json()["session_id"]

    for suffix, body in (("messages", {"message": "hi"}), ("approve", None), ("reject", None), ("modify", {"updates": {}})):
        kwargs = {"json": body} if body is not None else {}
        assert client.post(f"/api/v1/chat/sessions/{session_id}/{suffix}", **kwargs).status_code == 401, suffix


def test_a_live_session_is_not_reachable_by_a_different_user(client, monkeypatch):
    monkeypatch.setattr(server, "OrchestratorSession", _FakeSession)
    session_id = client.post("/api/v1/chat/sessions", headers=_auth("user-1")).json()["session_id"]
    server._SESSIONS[session_id].results.append(_done("secret"))

    resp = client.post(f"/api/v1/chat/sessions/{session_id}/messages", json={"message": "hi"}, headers=_auth("user-2"))

    assert resp.status_code == 404
    assert "secret" not in resp.text
    assert len(server._SESSIONS[session_id].results) == 1  # the run was never triggered


def test_a_new_session_uses_the_persisted_memory_session_id(client, monkeypatch):
    class _Persisted(_FakeSession):
        def __init__(self, token, **kwargs):
            super().__init__(token, **kwargs)
            self.memory_session_id = SESSION_ID

    monkeypatch.setattr(server, "OrchestratorSession", _Persisted)
    resp = client.post("/api/v1/chat/sessions", headers=_auth())

    assert resp.json()["session_id"] == SESSION_ID
    assert SESSION_ID in server._SESSIONS


def test_a_session_without_memory_falls_back_to_a_process_local_id(client, monkeypatch):
    monkeypatch.setattr(server, "OrchestratorSession", _FakeSession)  # memory_session_id is None
    session_id = client.post("/api/v1/chat/sessions", headers=_auth()).json()["session_id"]
    assert len(session_id) == 36 and session_id != SESSION_ID


# --- Resume after a restart ---------------------------------------------------------------


def test_a_session_this_process_lost_is_rebuilt_from_its_stored_history_on_the_same_id(client, monkeypatch):
    built: list[dict] = []

    class _Resumable(_FakeSession):
        def __init__(self, token, **kwargs):
            super().__init__(token, **kwargs)
            built.append(kwargs)
            self.results.append(_done("Welcome back"))

    checked: list[str] = []
    monkeypatch.setattr(server, "OrchestratorSession", _Resumable)
    _memory(monkeypatch, get_session_context_tool=lambda ctx, sid, **kw: checked.append(sid) or {"session": {}})
    assert SESSION_ID not in server._SESSIONS  # e.g. after a restart

    resp = client.post(f"/api/v1/chat/sessions/{SESSION_ID}/messages", json={"message": "hi again"}, headers=_auth())

    assert resp.status_code == 200
    tokens = [json.loads(line[len("data:") :])["text"] for line in resp.text.splitlines() if line.startswith("data:") and "\"text\"" in line]
    assert "".join(tokens) == "Welcome back"
    assert checked == [SESSION_ID]
    assert [k["memory_session_id"] for k in built] == [SESSION_ID]
    assert SESSION_ID in server._SESSIONS  # cached for the next turn


def test_resuming_someone_elses_or_a_missing_session_is_a_404_and_builds_nothing(client, monkeypatch):
    def not_found(ctx, sid, **kw):
        raise BackendAPIError(404, "Session not found")

    constructed = []
    monkeypatch.setattr(server, "OrchestratorSession", lambda *a, **k: constructed.append(1))
    _memory(monkeypatch, get_session_context_tool=not_found)

    resp = client.post(f"/api/v1/chat/sessions/{SESSION_ID}/messages", json={"message": "hi"}, headers=_auth())

    assert resp.status_code == 404
    assert constructed == []  # no orphan empty session is created behind a bad id


def test_a_malformed_session_id_is_a_404_without_calling_the_backend(client, monkeypatch):
    _memory(monkeypatch)  # any backend call would raise
    resp = client.post("/api/v1/chat/sessions/does-not-exist/messages", json={"message": "hi"}, headers=_auth())
    assert resp.status_code == 404


def test_if_the_orchestrator_could_not_resume_the_requested_id_the_request_fails_instead_of_forking(client, monkeypatch):
    class _Forked(_FakeSession):
        def __init__(self, token, **kwargs):
            super().__init__(token, **kwargs)
            self.memory_session_id = "11111111-1111-4111-8111-111111111111"  # a different, brand-new session

    monkeypatch.setattr(server, "OrchestratorSession", _Forked)
    _memory(monkeypatch, get_session_context_tool=lambda ctx, sid, **kw: {})

    resp = client.post(f"/api/v1/chat/sessions/{SESSION_ID}/messages", json={"message": "hi"}, headers=_auth())

    assert resp.status_code == 404
    assert SESSION_ID not in server._SESSIONS


def test_a_memory_outage_while_resuming_is_a_502_not_a_lost_conversation(client, monkeypatch):
    def down(ctx, sid, **kw):
        raise BackendAPIError(503, "down")

    _memory(monkeypatch, get_session_context_tool=down)
    resp = client.post(f"/api/v1/chat/sessions/{SESSION_ID}/messages", json={"message": "hi"}, headers=_auth())
    assert resp.status_code == 502


# --- Sidebar endpoints --------------------------------------------------------------------

SUMMARY = {
    "id": SESSION_ID,
    "title": "Overdue service",
    "message_count": 4,
    "created_at": "2026-09-30T08:00:00Z",
    "updated_at": "2026-09-30T09:00:00Z",
}


def test_list_sessions_returns_the_backends_list_for_the_callers_token(client, monkeypatch):
    seen = []
    _memory(monkeypatch, list_sessions_tool=lambda ctx, **kw: seen.append(ctx.user_id) or [SUMMARY])

    resp = client.get("/api/v1/chat/sessions", headers=_auth("user-7"))

    assert resp.status_code == 200
    assert resp.json() == [SUMMARY]
    assert seen == ["user-7"]


def test_the_session_endpoints_require_a_token(client, monkeypatch):
    _memory(monkeypatch)
    assert client.get("/api/v1/chat/sessions").status_code == 401
    assert client.get(f"/api/v1/chat/sessions/{SESSION_ID}/messages").status_code == 401
    assert client.patch(f"/api/v1/chat/sessions/{SESSION_ID}", json={"title": "x"}).status_code == 401
    assert client.get("/api/v1/chat/sessions", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401


def test_list_sessions_reports_a_backend_outage_as_502(client, monkeypatch):
    def down(ctx, **kw):
        raise BackendAPIError(500, "boom")

    _memory(monkeypatch, list_sessions_tool=down)
    assert client.get("/api/v1/chat/sessions", headers=_auth()).status_code == 502


def test_session_messages_returns_the_stored_transcript_without_internal_fields(client, monkeypatch):
    rows = [
        {"id": "m1", "role": "user", "content": "hi", "created_at": "2026-09-30T08:00:00Z", "is_summarized": True},
        {"id": "m2", "role": "assistant", "content": "hello", "created_at": "2026-09-30T08:00:05Z", "is_summarized": False},
    ]
    _memory(monkeypatch, get_session_messages_tool=lambda ctx, sid, **kw: rows)

    resp = client.get(f"/api/v1/chat/sessions/{SESSION_ID}/messages", headers=_auth())

    assert resp.status_code == 200
    assert [(m["role"], m["content"]) for m in resp.json()] == [("user", "hi"), ("assistant", "hello")]
    assert all("is_summarized" not in m for m in resp.json())


def test_session_messages_for_a_session_that_is_not_yours_is_a_404(client, monkeypatch):
    def not_found(ctx, sid, **kw):
        raise BackendAPIError(404, "Session not found")

    _memory(monkeypatch, get_session_messages_tool=not_found)
    assert client.get(f"/api/v1/chat/sessions/{SESSION_ID}/messages", headers=_auth()).status_code == 404


def test_rename_sends_the_title_to_the_backend_and_returns_the_result(client, monkeypatch):
    seen = []

    def rename(ctx, sid, title, **kw):
        seen.append((sid, title))
        return {"id": sid, "title": title, "running_summary": "", "summary_version": 0}

    _memory(monkeypatch, rename_session_tool=rename)

    resp = client.patch(f"/api/v1/chat/sessions/{SESSION_ID}", json={"title": "Fuel review"}, headers=_auth())

    assert resp.status_code == 200
    assert resp.json() == {"id": SESSION_ID, "title": "Fuel review"}
    assert seen == [(SESSION_ID, "Fuel review")]


@pytest.mark.parametrize("body", [{"title": ""}, {"title": "x" * 201}, {}])
def test_rename_rejects_bad_titles_before_calling_the_backend(client, monkeypatch, body):
    _memory(monkeypatch)  # a backend call would raise
    assert client.patch(f"/api/v1/chat/sessions/{SESSION_ID}", json=body, headers=_auth()).status_code == 422


@pytest.mark.parametrize("status", [404, 422])
def test_rename_passes_the_backends_404_and_422_through(client, monkeypatch, status):
    def rejected(ctx, sid, title, **kw):
        raise BackendAPIError(status, "nope")

    _memory(monkeypatch, rename_session_tool=rejected)
    assert client.patch(f"/api/v1/chat/sessions/{SESSION_ID}", json={"title": "   "}, headers=_auth()).status_code == status


# --- The orchestrator must actually be given memory ---------------------------------------


def test_sessions_are_opened_with_agent_memory_wired_in(client, monkeypatch):
    """OrchestratorDeps defaults memory to None, which silently disables persistence. The
    server has to pass it explicitly, or nothing is saved and nothing can be listed."""
    seen = []

    class _Capturing(_FakeSession):
        def __init__(self, token, **kwargs):
            super().__init__(token, **kwargs)
            seen.append(kwargs.get("deps"))

    sentinel = object()
    monkeypatch.setattr(server, "OrchestratorSession", _Capturing)
    monkeypatch.setattr(server, "_shared_memory", lambda: sentinel)

    client.post("/api/v1/chat/sessions", headers=_auth())

    assert seen and seen[0].memory is sentinel


def test_if_memory_cannot_start_chat_still_opens_but_unsaved(client, monkeypatch):
    server._shared_memory.cache_clear()
    monkeypatch.setattr(server, "AgentMemory", lambda: (_ for _ in ()).throw(RuntimeError("bad embedder config")))
    monkeypatch.setattr(server, "OrchestratorSession", _FakeSession)

    resp = client.post("/api/v1/chat/sessions", headers=_auth())

    assert resp.status_code == 200
    server._shared_memory.cache_clear()
