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
itself yet) — each runs in a thread pool. While it runs, every step the
session's FleetLiveObserver records (planning, each tool call, drafting, a
HITL pause) streams as an `activity` event; then the final response is
chunked word-by-word as `token` events, then `done` (or `approval_required`
on a HITL pause). This is a real response from a real multi-agent run, not
a fake typing effect over mock data — only the chunking is presentational.

Every session gets the full hook set (see _build_deps): agent memory, the
shared execution cache, the observer, the alert dispatcher, the
fact-checker, document search (search_documents) and RAG triad sampling. OrchestratorDeps defaults all of them to None, so leaving one
out here silently switches that hook off in production.
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

import io  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402

import openai  # noqa: E402

from fastapi import FastAPI, Header, HTTPException  # noqa: E402
from PIL import Image  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from sse_starlette.sse import EventSourceResponse  # noqa: E402

from core.llm_budget import get_tracker  # noqa: E402
from core.llm_failover import get_guard_chat_model  # noqa: E402
from core.tool_markup import strip_tool_markup  # noqa: E402
from mcp_server import memory_tools  # noqa: E402
from mcp_server.document_tools import BackendDocumentRetriever  # noqa: E402
from memory.service import AgentMemory  # noqa: E402
from orchestrator.cache import ExecutionCache  # noqa: E402
from orchestrator.callbacks import ORCHESTRATOR_AGENT, FleetLiveObserver  # noqa: E402
from orchestrator.fact_check import _default_fact_checker_llm  # noqa: E402
from orchestrator.graph import OrchestratorDeps, get_shared_llm  # noqa: E402
from orchestrator.rag_eval import RagTriadEvaluator  # noqa: E402
from orchestrator.session import OrchestratorSession, TurnResult  # noqa: E402
from orchestrator.webhooks import AlertDispatcher  # noqa: E402
from tools import api_client  # noqa: E402
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


# One cache for the whole process: keys are scoped by org AND user (reads are
# role-scoped by the backend), and a write in any conversation purges that
# org's namespace for every conversation, not just the one that wrote.
_EXECUTION_CACHE = ExecutionCache()

# Stateless: every search carries the caller's own token, and the backend
# decides which document types that role may see.
_DOCUMENT_RETRIEVER = BackendDocumentRetriever()
# Samples ~5% of document-grounded answers on a background thread; its judge
# LLM is built lazily on first use, so an unset key can't break startup.
_RAG_EVALUATOR = RagTriadEvaluator()


@lru_cache(maxsize=1)
def _fact_checker_llm():
    """The truth-checker runs after every synthesized answer. Fail-open like
    memory: if its model can't be built, answers go out unchecked rather than
    chat breaking."""
    try:
        return _default_fact_checker_llm()
    except Exception:  # noqa: BLE001
        logger.exception("fact-checker LLM could not start; answers will not be fact-checked")
        return None


@lru_cache(maxsize=1)
def _guard_llm():
    """The semantic input guard's model (orchestrator/security.py). Fail-open like the fact-checker: if it can't
    be built, or LLM_GUARD=off, the keyword allowlist alone decides the domain check."""
    if os.environ.get("LLM_GUARD", "on").strip().lower() in ("off", "0", "false", "no"):
        return None
    return get_guard_chat_model()


def _build_deps(context: AgentContext) -> OrchestratorDeps:
    return OrchestratorDeps(
        memory=_shared_memory(),
        cache=_EXECUTION_CACHE,
        # Per conversation: traces carry this user's org/user ids, and
        # _stream_turn points the observer's activity feed at the live response.
        observer=FleetLiveObserver(
            organization_id=context.organization_id, user_id=context.user_id, role=context.role
        ),
        webhooks=AlertDispatcher(),
        fact_checker_llm=_fact_checker_llm(),
        guard_llm=_guard_llm(),
        documents=_DOCUMENT_RETRIEVER,
        rag_evaluator=_RAG_EVALUATOR,
    )


def _open_session(token: str, **kwargs) -> OrchestratorSession:
    context = build_context(token)  # raises InvalidTokenError, which every caller maps to a 401
    return OrchestratorSession(token=token, deps=_build_deps(context), **kwargs)


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


# Exactly what the backend's POST /api/v1/uploads/image returns. Anything else
# is rejected, so this server only ever fetches its own backend's upload store
# (never an arbitrary URL -- no SSRF).
_ATTACHMENT_PATH = r"^/uploads/incidents/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(jpg|png|webp)$"
_ATTACHMENT_MIME = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


class MessageRequest(BaseModel):
    message: str = Field(max_length=4000)
    attachment_url: str | None = Field(default=None, pattern=_ATTACHMENT_PATH)


def _load_attachment(path: str) -> tuple[bytes, str]:
    """The uploaded image's bytes and MIME type, ready for the vision models.
    Those accept JPEG/PNG only, so a WebP is re-encoded as PNG here."""
    try:
        response = api_client._http_client().get(f"{api_client._base_url()}{path}", timeout=10.0)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="Couldn't read the attached image.") from exc
    if response.status_code == 404:
        raise HTTPException(status_code=422, detail="The attached image no longer exists; attach it again.")
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Couldn't read the attached image.")

    mime = _ATTACHMENT_MIME[path.rsplit(".", 1)[1]]
    if mime != "image/webp":
        return response.content, mime
    try:
        with Image.open(io.BytesIO(response.content)) as image:
            converted = io.BytesIO()
            image.save(converted, format="PNG")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="The attached WebP image couldn't be decoded.") from exc
    return converted.getvalue(), "image/png"


class ModifyRequest(BaseModel):
    updates: dict


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data)}


# The approval card needs the question and the tool name. The paused sub-agent's own state also carries the caller's
# JWT and, in any photo flow, the raw image bytes: neither belongs in a browser, and bytes are not even JSON (they
# crashed the stream, so a receipt never reached its approval step).
_HITL_HIDDEN_KEYS = frozenset({"token", "image_bytes", "mime_type"})


def _amount(value: object) -> str:
    try:
        return f"{float(value):,.2f}".rstrip("0").rstrip(".")  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)


def _describe_pending_fuel_log(state: dict) -> str | None:
    """What the user is about to approve, for a fuel log the agent has prepared: they should see the figures, not a
    generic prompt."""
    record = state.get("sanitized")
    if not isinstance(record, dict) or "liters_filled" not in record or "total_cost" not in record:
        return None
    vehicle = state.get("vehicle_plate") or "this vehicle"
    parts = [f"{_amount(record['liters_filled'])} L"]
    if record.get("price_per_liter") is not None:
        parts.append(f"at Rs {_amount(record['price_per_liter'])}/L")
    parts.append(f"= Rs {_amount(record['total_cost'])}")
    when = f" on {record['date']}" if record.get("date") else ""
    return f"Record this fuel fill for {vehicle}: {' '.join(parts)}{when}?"


def _client_hitl_state(hitl: dict | None) -> dict | None:
    """The approval payload as the browser may see it: no secrets or binary data, only JSON types."""
    if not hitl:
        return hitl
    safe = dict(hitl)
    if isinstance(safe.get("state"), dict):
        safe["state"] = {k: v for k, v in safe["state"].items() if k not in _HITL_HIDDEN_KEYS}
    safe = json.loads(json.dumps(safe, default=str))  # dates and Decimals become strings
    if not safe.get("approval_prompt"):
        prompt = _describe_pending_fuel_log(safe.get("state") or {})
        if prompt:
            safe["approval_prompt"] = prompt
    return safe


_GENERIC_TURN_ERROR = "The AI assistant hit an unexpected error. Please try again."
_RETRY_AFTER = re.compile(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", re.IGNORECASE)


def _wait_phrase(hours: str | None, minutes: str | None, seconds: str | None) -> str | None:
    total = int(hours or 0) * 3600 + int(minutes or 0) * 60 + math.ceil(float(seconds or 0))
    if total <= 0:
        return None
    if total < 90:
        return f"{total} seconds"
    if total < 5400:
        return f"{math.ceil(total / 60)} minutes"
    return f"{math.ceil(total / 3600)} hours"


def _turn_error_message(exc: BaseException) -> str:
    """A user-facing reason for a failed turn. Only ever fixed wording plus the provider's
    retry hint -- never the raw exception text, which can carry account ids and internals."""
    if isinstance(exc, openai.RateLimitError):
        match = _RETRY_AFTER.search(str(exc))
        phrase = _wait_phrase(*match.groups()) if match else None
        wait = f" Try again in about {phrase}." if phrase else " Please try again later."
        return f"The AI model's usage limit has been reached, so it can't answer right now.{wait}"
    if isinstance(exc, openai.BadRequestError):
        return "The AI model produced an invalid request for that question. Please try rephrasing it."
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return "The AI model couldn't be reached. Please try again in a moment."
    return _GENERIC_TURN_ERROR


_OPENING_STEP = "Reading your message…"

# The agent keys the frontend knows (lib/schemas/chat.ts agentKeySchema).
# Anything else (e.g. a tool name the LLM hallucinated) is shown as the
# orchestrator's own step rather than breaking the client's event parsing.
_ACTIVITY_AGENTS = frozenset({
    "foundation", "fuel", "maintenance", "accountability", "insights", "assignment",
    "search_documents", "update_memory", ORCHESTRATOR_AGENT,
})


def _activity(step: tuple[str, str], *, done: bool) -> dict:
    agent, text = step
    return _sse("activity", {"agent": agent if agent in _ACTIVITY_AGENTS else ORCHESTRATOR_AGENT, "step": text, "done": done})


async def _stream_turn(session: OrchestratorSession, run_turn) -> EventSourceResponse:
    """Runs a blocking OrchestratorSession call in a thread and streams it as
    SSE: each real step the FleetLiveObserver records (planning, each tool
    call, drafting, a HITL pause) as an `activity` event while it runs -- the
    previous step re-sent with done=true as the next one starts -- then the
    final text chunked as `token` events, then `done` or `approval_required`."""

    async def events():
        loop = asyncio.get_running_loop()
        steps: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        observer = getattr(getattr(session, "deps", None), "observer", None)
        if observer is not None:
            # Called from the worker thread running the turn.
            observer.activity_sink = lambda agent, text: loop.call_soon_threadsafe(steps.put_nowait, (agent, text))

        current = (ORCHESTRATOR_AGENT, _OPENING_STEP)
        yield _activity(current, done=False)
        turn = loop.run_in_executor(None, run_turn)
        try:
            while True:
                next_step = asyncio.ensure_future(steps.get())
                finished, _ = await asyncio.wait({turn, next_step}, return_when=asyncio.FIRST_COMPLETED)
                if next_step not in finished:
                    next_step.cancel()
                    break
                step = next_step.result()
                if step != current:
                    yield _activity(current, done=True)
                    yield _activity(step, done=False)
                    current = step
            while not steps.empty():  # steps recorded in the turn's final instant
                step = steps.get_nowait()
                if step != current:
                    yield _activity(current, done=True)
                    yield _activity(step, done=False)
                    current = step
            result: TurnResult = turn.result()
        except Exception as exc:  # noqa: BLE001 — never leak a stack trace to the browser
            logger.exception("chat turn failed")
            yield _sse("error", {"message": _turn_error_message(exc)})
            return
        finally:
            if observer is not None:
                observer.activity_sink = None

        yield _activity(current, done=True)

        if result.status == "awaiting_approval":
            yield _sse("approval_required", {"hitl_state": _client_hitl_state(result.hitl_state)})
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
    if body.attachment_url is None:
        return await _stream_turn(session, lambda: session.run(body.message))

    # Read before streaming starts, so a missing/bad image is a plain 4xx the
    # client can show, not an error in the middle of a stream.
    image_bytes, mime_type = await asyncio.to_thread(_load_attachment, body.attachment_url)
    return await _stream_turn(
        session,
        lambda: session.run(body.message, image_bytes=image_bytes, mime_type=mime_type, attachment_url=body.attachment_url),
    )


@app.post("/api/v1/chat/sessions/{session_id}/approve")
async def approve(session_id: str, authorization: str | None = Header(default=None)) -> EventSourceResponse:
    session = await asyncio.to_thread(_get_session, session_id, authorization)
    return await _stream_turn(session, session.approve)


@app.post("/api/v1/chat/sessions/{session_id}/modify")
async def modify(session_id: str, body: ModifyRequest, authorization: str | None = Header(default=None)) -> EventSourceResponse:
    session = await asyncio.to_thread(_get_session, session_id, authorization)
    return await _stream_turn(session, lambda: session.modify(body.updates))


@app.post("/api/v1/chat/sessions/{session_id}/reject")
async def reject(session_id: str, authorization: str | None = Header(default=None)) -> EventSourceResponse:
    session = await asyncio.to_thread(_get_session, session_id, authorization)
    return await _stream_turn(session, session.reject)


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


def _visible_messages(rows: list[dict]) -> list[dict]:
    """Assistant replies saved before the tool-markup guard may still hold raw tool-call syntax; the transcript
    shows only the natural language (a reply that was nothing else is left out)."""
    visible: list[dict] = []
    for row in rows:
        if row.get("role") == "assistant":
            content = strip_tool_markup(row.get("content") or "")
            if not content:
                continue
            row = {**row, "content": content}
        visible.append(row)
    return visible


@app.get("/api/v1/chat/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
def get_session_messages(session_id: str, authorization: str | None = Header(default=None)) -> list[dict]:
    """The stored transcript, for showing a past conversation when it is opened."""
    _, context = _authenticate(authorization)
    try:
        rows = memory_tools.get_session_messages_tool(context, session_id)
    except BackendAPIError as exc:
        _raise_for_backend(exc)
        raise
    return _visible_messages(rows)


@app.patch("/api/v1/chat/sessions/{session_id}", response_model=RenameSessionResponse)
def rename_session(session_id: str, body: RenameSessionRequest, authorization: str | None = Header(default=None)) -> dict:
    _, context = _authenticate(authorization)
    try:
        renamed = memory_tools.rename_session_tool(context, session_id, body.title)
    except BackendAPIError as exc:
        _raise_for_backend(exc)
        raise
    return {"id": renamed["id"], "title": renamed["title"]}


@app.delete("/api/v1/chat/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, authorization: str | None = Header(default=None)) -> None:
    """Deletes one of the caller's conversations (the backend enforces ownership:
    someone else's id is a 404) and drops any live copy this process holds, so
    a stale OrchestratorSession can't resurrect it on the next message."""
    _, context = _authenticate(authorization)
    try:
        memory_tools.delete_session_tool(context, session_id)
    except BackendAPIError as exc:
        _raise_for_backend(exc)
        raise
    live = _SESSIONS.get(session_id)
    if live is not None and live.user_id == context.user_id:
        _SESSIONS.pop(session_id, None)
        _SESSION_TOUCHED.pop(session_id, None)


@app.get("/health")
def health() -> dict:
    try:
        models = get_shared_llm().status()
    except Exception:  # noqa: BLE001 -- e.g. no API keys configured: still report the rest
        models = []
    return {"status": "ok", "active_sessions": len(_SESSIONS), "llm_models": models, "llm_usage": get_tracker().snapshot()}
