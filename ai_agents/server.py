"""HTTP/SSE server for the Grand Orchestrator (`orchestrator.session.OrchestratorSession`).

Nothing before this file exposed the orchestrator over HTTP at all (see
CLAUDE.md's cross-module boundary note, and plans/07-ai-surfaces.md in
`frontend`, which built the whole chat UI against a typed "unavailable"
stub for exactly that reason). This is the first real wire-up: a thin
FastAPI app that owns per-session `OrchestratorSession` instances in memory
and streams each turn back as Server-Sent Events.

Auth: the caller's own backend-issued JWT is passed straight through as a
Bearer token — `tools.auth_context.build_context` decodes the same `sub`/
`org`/`role` claims `backend/app/core/security.py` signs, so this server
never re-authenticates the user itself; the backend remains the signing/
verification authority (see auth_context.py's own docstring). Every endpoint
that touches a session requires that token, and a session is only ever
reachable by the user it belongs to.

Session identity: a chat session's id IS the id of its persisted backend memory
session (`/api/v1/memory/sessions`). That is what makes conversations survive
restarts and appear in the sidebar: listing, renaming and reading a transcript are
thin calls to the backend memory API (ai_agents never touches Postgres itself), and
sending a message to a session this process no longer holds rebuilds it from the
stored history. The orchestrator graph itself is not checkpointed (only sub-agent
graphs are), so the one thing a restart loses is a pending human-approval pause.

Streaming model: `OrchestratorSession.run/approve/modify/reject` are
synchronous, blocking calls (no token-level streaming inside the graph
itself yet) — each runs in a thread pool, and the *result* is what streams
back: one `activity` event while it's in flight, then the final response
chunked word-by-word as `token` events so the UI has something to animate,
then `done` (or `approval_required` on a HITL pause). This is a real
response from a real multi-agent run, not a fake typing effect over mock
data — only the chunking is presentational.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from functools import lru_cache
from typing import Literal

from dotenv import load_dotenv

# Nothing else in this codebase calls load_dotenv() (verified: no other
# call site exists) — every provider key in core/llm_config.py reads
# straight from os.environ, so this has to run before the first
# OrchestratorDeps() is constructed (create_session, below), which is when
# its default_factory actually builds the Groq-backed LLM client.
load_dotenv()

from fastapi import FastAPI, Header, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from sse_starlette.sse import EventSourceResponse  # noqa: E402

from mcp_server import memory_tools  # noqa: E402
from memory.service import AgentMemory  # noqa: E402
from orchestrator.graph import OrchestratorDeps  # noqa: E402
from orchestrator.session import OrchestratorSession, TurnResult  # noqa: E402
from tools.api_client import BackendAPIError  # noqa: E402
from tools.auth_context import AgentContext, InvalidTokenError, build_context  # noqa: E402

logger = logging.getLogger("fleet.chat_server")

app = FastAPI(title="Fleet AI Agents — Chat")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Per-process cache of live OrchestratorSessions (their scratchpad and any pending
# approval live here). See the module docstring: the conversation itself is persisted,
# so an evicted or lost entry is rebuilt from the database by _resume_session.
_SESSIONS: dict[str, OrchestratorSession] = {}
_SESSION_TTL_SECONDS = 60 * 60
_SESSION_TOUCHED: dict[str, float] = {}


def _get_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token.")
    return authorization.split(" ", 1)[1]


def _authenticate(authorization: str | None) -> tuple[str, AgentContext]:
    token = _get_token(authorization)
    try:
        return token, build_context(token)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _evict_stale_sessions() -> None:
    now = time.time()
    stale = [sid for sid, touched in _SESSION_TOUCHED.items() if now - touched > _SESSION_TTL_SECONDS]
    for sid in stale:
        _SESSIONS.pop(sid, None)
        _SESSION_TOUCHED.pop(sid, None)


def _register(session_id: str, session: OrchestratorSession) -> None:
    _evict_stale_sessions()
    _SESSIONS[session_id] = session
    _SESSION_TOUCHED[session_id] = time.time()


@lru_cache(maxsize=1)
def _shared_memory() -> AgentMemory | None:
    """The one AgentMemory every conversation uses (its single background worker is what keeps
    a conversation's messages in the order they were said). Without it the orchestrator runs
    with no memory at all -- OrchestratorDeps defaults it to None -- so nothing is saved and
    there is nothing to list or resume. If it cannot start (e.g. a misconfigured embedder),
    chat still works, just unsaved."""
    try:
        return AgentMemory()
    except Exception:  # noqa: BLE001
        logger.exception("agent memory could not start; conversations will not be saved")
        return None


def _open_session(token: str, **kwargs) -> OrchestratorSession:
    return OrchestratorSession(token=token, deps=OrchestratorDeps(memory=_shared_memory()), **kwargs)


def _raise_for_backend(exc: BackendAPIError) -> None:
    """Pass the backend's client errors through; anything else is our upstream failing."""
    if exc.status_code in (401, 403, 404, 422):
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    raise HTTPException(status_code=502, detail="The memory service is unavailable.") from exc


class CreateSessionResponse(BaseModel):
    session_id: str


@app.post("/api/v1/chat/sessions", response_model=CreateSessionResponse)
def create_session(authorization: str | None = Header(default=None)) -> CreateSessionResponse:
    token = _get_token(authorization)
    try:
        session = _open_session(token)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    # The persisted memory session's id, so this conversation is listable and resumable.
    # Only if memory is unreachable does it fall back to an id that lives and dies with this process.
    session_id = session.memory_session_id or str(uuid.uuid4())
    _register(session_id, session)
    return CreateSessionResponse(session_id=session_id)


def _resume_session(session_id: str, token: str, context: AgentContext) -> OrchestratorSession:
    """Rebuild a conversation this process isn't holding from its stored history.

    Anything that isn't the caller's own persisted session is a 404 (the backend
    answers 404 for another user's session too, so ids can't be probed)."""
    try:
        uuid.UUID(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Unknown or expired chat session.") from exc
    try:
        # Checked first so a bad id doesn't leave an orphan empty session behind: the
        # OrchestratorSession constructor quietly starts a new one when it can't resume.
        memory_tools.get_session_context_tool(context, session_id)
    except BackendAPIError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="Unknown or expired chat session.") from exc
        _raise_for_backend(exc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("could not reach the memory service while resuming %s", session_id)
        raise HTTPException(status_code=502, detail="The memory service is unavailable.") from exc
    try:
        session = _open_session(token, memory_session_id=session_id)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    if session.memory_session_id != session_id:
        raise HTTPException(status_code=404, detail="Unknown or expired chat session.")
    _register(session_id, session)
    return session


def _get_session(session_id: str, authorization: str | None) -> OrchestratorSession:
    token, context = _authenticate(authorization)
    session = _SESSIONS.get(session_id)
    if session is not None:
        if session.user_id != context.user_id:
            # Same answer as an unknown id: don't reveal that someone else's session exists.
            raise HTTPException(status_code=404, detail="Unknown or expired chat session.")
        _SESSION_TOUCHED[session_id] = time.time()
        return session
    return _resume_session(session_id, token, context)


class MessageRequest(BaseModel):
    message: str


class ModifyRequest(BaseModel):
    updates: dict


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data)}


async def _stream_turn(run_turn) -> EventSourceResponse:
    """Runs a blocking OrchestratorSession call in a thread and streams the
    result as SSE: `activity` while it's running, the final text chunked as
    `token` events, then `done` or `approval_required`."""

    async def events():
        yield _sse("activity", {"agent": "foundation", "step": "Thinking…", "done": False})
        loop = asyncio.get_event_loop()
        try:
            result: TurnResult = await loop.run_in_executor(None, run_turn)
        except Exception:  # noqa: BLE001 — never leak a stack trace to the browser
            logger.exception("chat turn failed")
            yield _sse("error", {"message": "The AI assistant hit an unexpected error. Please try again."})
            return

        yield _sse("activity", {"agent": "foundation", "step": "Thinking…", "done": True})

        if result.status == "awaiting_approval":
            yield _sse("approval_required", {"hitl_state": result.hitl_state})
            return

        text = result.final_response or ""
        words = text.split(" ")
        for i, word in enumerate(words):
            chunk = word if i == len(words) - 1 else word + " "
            yield _sse("token", {"text": chunk})
            await asyncio.sleep(0.02)

        yield _sse("done", {"status": result.status})

    return EventSourceResponse(events())


@app.post("/api/v1/chat/sessions/{session_id}/messages")
async def send_message(
    session_id: str, body: MessageRequest, authorization: str | None = Header(default=None)
) -> EventSourceResponse:
    # Resolving may call the backend (to resume), so keep it off the event loop.
    session = await asyncio.to_thread(_get_session, session_id, authorization)
    return await _stream_turn(lambda: session.run(body.message))


@app.post("/api/v1/chat/sessions/{session_id}/approve")
async def approve(session_id: str, authorization: str | None = Header(default=None)) -> EventSourceResponse:
    session = await asyncio.to_thread(_get_session, session_id, authorization)
    return await _stream_turn(session.approve)


@app.post("/api/v1/chat/sessions/{session_id}/modify")
async def modify(session_id: str, body: ModifyRequest, authorization: str | None = Header(default=None)) -> EventSourceResponse:
    session = await asyncio.to_thread(_get_session, session_id, authorization)
    return await _stream_turn(lambda: session.modify(body.updates))


@app.post("/api/v1/chat/sessions/{session_id}/reject")
async def reject(session_id: str, authorization: str | None = Header(default=None)) -> EventSourceResponse:
    session = await asyncio.to_thread(_get_session, session_id, authorization)
    return await _stream_turn(session.reject)


# --- Session management (sidebar) -------------------------------------------------------


class ChatSessionSummary(BaseModel):
    id: str
    title: str
    message_count: int
    created_at: str
    updated_at: str


class ChatMessageOut(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: str


class RenameSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class RenameSessionResponse(BaseModel):
    id: str
    title: str


@app.get("/api/v1/chat/sessions", response_model=list[ChatSessionSummary])
def list_sessions(authorization: str | None = Header(default=None)) -> list[dict]:
    """The caller's own conversations, most recently active first. A conversation's title is
    set by the backend from its first message the moment that message is recorded."""
    _, context = _authenticate(authorization)
    try:
        return memory_tools.list_sessions_tool(context)
    except BackendAPIError as exc:
        _raise_for_backend(exc)
        raise


@app.get("/api/v1/chat/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
def get_session_messages(session_id: str, authorization: str | None = Header(default=None)) -> list[dict]:
    """The stored transcript, for showing a past conversation when it is opened."""
    _, context = _authenticate(authorization)
    try:
        return memory_tools.get_session_messages_tool(context, session_id)
    except BackendAPIError as exc:
        _raise_for_backend(exc)
        raise


@app.patch("/api/v1/chat/sessions/{session_id}", response_model=RenameSessionResponse)
def rename_session(session_id: str, body: RenameSessionRequest, authorization: str | None = Header(default=None)) -> dict:
    _, context = _authenticate(authorization)
    try:
        renamed = memory_tools.rename_session_tool(context, session_id, body.title)
    except BackendAPIError as exc:
        _raise_for_backend(exc)
        raise
    return {"id": renamed["id"], "title": renamed["title"]}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "active_sessions": len(_SESSIONS)}
