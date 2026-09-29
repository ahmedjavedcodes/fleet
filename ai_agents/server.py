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
verification authority (see auth_context.py's own docstring).

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

from dotenv import load_dotenv

# Nothing else in this codebase calls load_dotenv() (verified: no other
# call site exists) — every provider key in core/llm_config.py reads
# straight from os.environ, so this has to run before the first
# OrchestratorDeps() is constructed (create_session, below), which is when
# its default_factory actually builds the Groq-backed LLM client.
load_dotenv()

from fastapi import FastAPI, Header, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from sse_starlette.sse import EventSourceResponse  # noqa: E402

from orchestrator.session import OrchestratorSession, TurnResult  # noqa: E402
from tools.auth_context import InvalidTokenError  # noqa: E402

logger = logging.getLogger("fleet.chat_server")

app = FastAPI(title="Fleet AI Agents — Chat")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Per-process, in-memory session store. A session holds real conversation
# state (chat_history, scratchpad) and is not persisted — restarting this
# process loses in-flight conversations, same tradeoff OrchestratorSession
# itself documents for its memory_session_id fallback.
_SESSIONS: dict[str, OrchestratorSession] = {}
_SESSION_TTL_SECONDS = 60 * 60
_SESSION_TOUCHED: dict[str, float] = {}


def _get_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token.")
    return authorization.split(" ", 1)[1]


def _evict_stale_sessions() -> None:
    now = time.time()
    stale = [sid for sid, touched in _SESSION_TOUCHED.items() if now - touched > _SESSION_TTL_SECONDS]
    for sid in stale:
        _SESSIONS.pop(sid, None)
        _SESSION_TOUCHED.pop(sid, None)


class CreateSessionResponse(BaseModel):
    session_id: str


@app.post("/api/v1/chat/sessions", response_model=CreateSessionResponse)
def create_session(authorization: str | None = Header(default=None)) -> CreateSessionResponse:
    token = _get_token(authorization)
    try:
        session = OrchestratorSession(token=token)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _evict_stale_sessions()
    session_id = str(uuid.uuid4())
    _SESSIONS[session_id] = session
    _SESSION_TOUCHED[session_id] = time.time()
    return CreateSessionResponse(session_id=session_id)


def _get_session(session_id: str) -> OrchestratorSession:
    session = _SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown or expired chat session.")
    _SESSION_TOUCHED[session_id] = time.time()
    return session


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
async def send_message(session_id: str, body: MessageRequest) -> EventSourceResponse:
    session = _get_session(session_id)
    return await _stream_turn(lambda: session.run(body.message))


@app.post("/api/v1/chat/sessions/{session_id}/approve")
async def approve(session_id: str) -> EventSourceResponse:
    session = _get_session(session_id)
    return await _stream_turn(session.approve)


@app.post("/api/v1/chat/sessions/{session_id}/modify")
async def modify(session_id: str, body: ModifyRequest) -> EventSourceResponse:
    session = _get_session(session_id)
    return await _stream_turn(lambda: session.modify(body.updates))


@app.post("/api/v1/chat/sessions/{session_id}/reject")
async def reject(session_id: str) -> EventSourceResponse:
    session = _get_session(session_id)
    return await _stream_turn(session.reject)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "active_sessions": len(_SESSIONS)}
