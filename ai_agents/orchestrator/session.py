"""OrchestratorSession: the stateful, resumable conversation wrapper.

Owns one OrchestratorState across multiple user turns and HITL pauses --
this is what a chat endpoint (none exists yet -- see CLAUDE.md's
cross-module boundary note) would hold per conversation. auth_context is
set once at construction from the caller's own JWT and never mutated
afterward, matching FR 2's "Immutable RBAC Injection": the routing LLM
never sees it, only tool names/schemas.

Resuming after a HITL pause does NOT use LangGraph's own checkpoint/resume
on the *orchestrator's* graph -- only each *sub-agent's* graph is
checkpointed (runner.py). The orchestrator loop itself just re-invokes
build_orchestrator_graph() fresh with the updated scratchpad; since its
entry point is `plan`, this naturally continues the ReAct loop (the LLM
sees the just-resolved observation and decides whether to chain another
hop or synthesize).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import openai
from pydantic import ValidationError

from core.llm_failover import BudgetExhausted, InvalidModelOutput
from core.tool_markup import strip_tool_markup
from orchestrator.offline import answer_offline

from orchestrator.graph import HISTORY_WINDOW, OrchestratorDeps, _format_observation, get_compiled_orchestrator_graph
from orchestrator.security import DEFAULT_SECURITY_CONFIG, SecurityConfig, scan_user_input
from orchestrator.state import OrchestratorState
from orchestrator.tool_errors import tool_failure_observation
from orchestrator.tool_schemas import DOCUMENT_TOOL_NAME, MEMORY_TOOL_NAME, UpdateMemoryInput
from tools.api_client import BackendAPIError
from tools.auth_context import build_context

logger = logging.getLogger("fleet.security")
memory_logger = logging.getLogger("fleet.memory")

# Shown only if a reply turns out to have been nothing but raw tool-call syntax.
TOOL_MARKUP_FALLBACK = "I couldn't complete that request. Please try again."


@dataclass
class TurnResult:
    status: str  # "done" | "halted" | "awaiting_approval"
    final_response: str | None
    hitl_state: dict[str, Any] | None
    state: OrchestratorState


def _clean_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    """Stored assistant replies from before the tool-markup guard may still contain raw tool-call syntax. Fed back
    to the model as history it teaches the model to keep writing it, so it is removed on the way in (a reply that
    was nothing else is dropped)."""
    cleaned: list[dict[str, str]] = []
    for message in history:
        content = message.get("content") or ""
        if message.get("role") == "assistant":
            content = strip_tool_markup(content)
            if not content:
                continue
        cleaned.append({**message, "content": content})
    return cleaned


def _await_sync(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a coroutine to completion from synchronous code. OrchestratorSession.run is synchronous (the server
    runs it on a worker thread and the LangGraph graph is invoked synchronously), but the security pre-hook is
    async so it can await the guard model under a strict timeout. A plain asyncio.run suffices on a worker
    thread; if a caller does have an event loop running on this thread, the coroutine gets a thread of its own
    rather than failing with "asyncio.run() cannot be called from a running event loop"."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _is_model_outage(exc: BaseException) -> bool:
    """True when the failure is the language models being unavailable (as opposed to a bug)."""
    return isinstance(exc, (openai.APIError, InvalidModelOutput, BudgetExhausted))


class OrchestratorSession:
    def __init__(
        self,
        token: str,
        *,
        deps: OrchestratorDeps | None = None,
        security_config: SecurityConfig = DEFAULT_SECURITY_CONFIG,
        memory_session_id: str | None = None,
    ):
        """memory_session_id resumes an earlier conversation's short-term
        memory (agent-memory.md §2A); omitted, a new backend session is
        created. Both are fail-open: if the memory backend is unreachable the
        conversation still works, just without persistence."""
        context = build_context(token)
        self._context = context
        self.deps = deps or OrchestratorDeps()
        self.security_config = security_config
        self._graph = get_compiled_orchestrator_graph(self.deps)
        chat_history: list[dict[str, str]] = []
        self.memory_session_id: str | None = None
        if self.deps.memory is not None:
            self.memory_session_id, chat_history = self._open_memory_session(memory_session_id)
        self.state: OrchestratorState = {
            "auth_context": {
                "token": token,
                "role": context.role,
                "user_id": context.user_id,
                "organization_id": context.organization_id,
            },
            "chat_history": chat_history,
            "scratchpad": [],
            "active_tool_calls": [],
            "hitl_state": None,
            "final_response": None,
            "hop_count": 0,
            "stage": "planning",
            "halt_reason": None,
            "memory_session_id": self.memory_session_id,
        }

    @property
    def user_id(self) -> str:
        """The authenticated user this conversation belongs to (from the JWT it was opened with)."""
        return self._context.user_id

    def _open_memory_session(self, requested_id: str | None) -> tuple[str | None, list[dict[str, str]]]:
        memory = self.deps.memory
        if requested_id:
            try:
                return requested_id, _clean_history(memory.load_history(self._context, requested_id))
            except Exception:  # noqa: BLE001 -- e.g. 404 for someone else's session id
                memory_logger.warning("memory: could not resume session %s, starting a new one", requested_id)
        try:
            return memory.start_session(self._context), []
        except Exception:  # noqa: BLE001
            memory_logger.exception("memory: could not create a session; continuing without persistence")
            return None, []

    def _record(self, role: str, content: str) -> None:
        if self.deps.memory is not None and self.memory_session_id and content:
            self.deps.memory.record_message(self._context, self.memory_session_id, role, content)

    def run(
        self,
        message: str,
        *,
        image_bytes: bytes | None = None,
        mime_type: str | None = None,
        attachment_url: str | None = None,
        referenced_documents: list[dict[str, str]] | None = None,
    ) -> TurnResult:
        """image_bytes/mime_type: a photo attached to this turn, handed to
        whichever vision sub-agent the planner routes it to. attachment_url:
        where that photo is stored, so e.g. a filed incident can link it.
        referenced_documents: [{"id", "filename"}] the user @-mentioned (already checked against their access):
        document search this turn is restricted to exactly them."""
        if self.deps.observer is not None:
            self.deps.observer.start_turn()  # FR 4: a fresh trace_id per session turn

        # Security pre-hook (execution-pre_hooks.md §2): a violation halts
        # BEFORE build_orchestrator_graph is ever invoked -- no LLM call,
        # no state mutation beyond appending the rejected turn to history.
        violation = _await_sync(
            scan_user_input(
                message, config=self.security_config, guard_llm=self.deps.guard_llm,
                # A photo or a mentioned document says what the message is about, so "summarize this" is on-topic;
                # the injection checks still apply.
                has_attachment=image_bytes is not None or bool(referenced_documents),
            )
        )
        if violation is not None:
            logger.warning("Security pre-hook rejected input: %s", violation.reason)
            chat_history = list(self.state.get("chat_history") or []) + [
                {"role": "user", "content": message},
                {"role": "assistant", "content": violation.rejection_message},
            ]
            self.state = {**self.state, "chat_history": chat_history}
            return TurnResult(status="halted", final_response=violation.rejection_message, hitl_state=None, state=self.state)

        # Sliding window: the model sees only the last HISTORY_WINDOW messages anyway (older context lives in the
        # memory summary), so the in-process copy is cut to twice that instead of growing for the whole session.
        chat_history = (list(self.state.get("chat_history") or []) + [{"role": "user", "content": message}])[-2 * HISTORY_WINDOW :]
        input_state = {
            **self.state,
            "chat_history": chat_history,
            "scratchpad": [],  # fresh per user turn -- prior turns live in chat_history
            "hop_count": 0,
            "hitl_state": None,
            "final_response": None,
            "_pending_image_bytes": image_bytes,
            "_pending_mime_type": mime_type,
            # Fresh per user turn, same reasoning as hop_count above -- a
            # prior turn's fact-check retry count must not carry over and
            # silently disable the guardrail on this turn (execution-post_hooks.md §4).
            "_fact_check_retries": 0,
            "_fact_check_warning": None,
            "memory_context": None,  # fetch_memory refetches once per user turn
            "_pending_memory_facts": None,
            "_turn_wrote": False,
            "_jev_routed": False,
            "_routed_direct": False,
            "_restrict_tools": None,
            "_deterministic_reply": None,
            "_pending_attachment_url": attachment_url,
            "_referenced_documents": list(referenced_documents or []),
        }
        self._record("user", message)
        try:
            return self._settle(self._graph.invoke(input_state))
        except Exception as exc:  # noqa: BLE001
            if not _is_model_outage(exc):
                raise
            # Every LLM failed. A plain read can still be answered from the records directly.
            memory_logger.warning("all LLM providers failed (%s); trying the offline answer", type(exc).__name__)
            try:
                answer = answer_offline(message, self.deps.runner, self.state["auth_context"]["token"])
            except Exception:  # noqa: BLE001 -- the fallback must never mask the original error
                memory_logger.exception("offline fallback failed")
                answer = None
            if answer is None:
                raise
            return self._settle({**input_state, "final_response": answer, "stage": "done"})

    def approve(self) -> TurnResult:
        return self._resume(updates=None, rejected=False)

    def modify(self, updates: dict[str, Any]) -> TurnResult:
        return self._resume(updates=updates, rejected=False)

    def reject(self) -> TurnResult:
        return self._resume(updates=None, rejected=True)

    def _resume(self, *, updates: dict[str, Any] | None, rejected: bool) -> TurnResult:
        hitl = self.state.get("hitl_state")
        if not hitl:
            raise RuntimeError("No HITL checkpoint is pending on this session.")

        scratchpad = list(self.state.get("scratchpad") or [])
        hop = self.state.get("hop_count", 0) + 1

        if hitl["agent_name"] == MEMORY_TOOL_NAME:
            observation, trace_status = self._resolve_memory_approval(hitl, updates=updates, rejected=rejected)
            raw_result = None
        elif rejected:
            observation = f"{hitl['agent_name']} aborted by the user before the write was made."
            trace_status = "halted"
            raw_result = None
        else:
            try:
                result = self.deps.runner.resume(hitl["agent_name"], hitl["thread_id"], updates=updates)
            except Exception as exc:  # noqa: BLE001 -- an outage mid-approval must not end the turn
                observation = tool_failure_observation(hitl["agent_name"], exc)
                trace_status = "halted"
                raw_result = None
            else:
                observation = _format_observation(hitl["agent_name"], result)
                trace_status = result.status
                raw_result = result.state

        scratchpad.append({"hop": hop, "tool": hitl["agent_name"], "args": updates or {}, "observation": observation})
        if self.deps.observer is not None:
            self.deps.observer.record_tool_result(
                hitl["thread_id"], hitl["agent_name"], updates or {}, attempt=1, status=trace_status,
                observation_text=observation, raw_result=raw_result,
            )

        input_state = {**self.state, "scratchpad": scratchpad, "hop_count": hop, "hitl_state": None, "final_response": None}
        return self._settle(self._graph.invoke(input_state))

    def _resolve_memory_approval(
        self, hitl: dict[str, Any], *, updates: dict[str, Any] | None, rejected: bool
    ) -> tuple[str, str]:
        """The only path by which an LLM-proposed fact reaches the vault:
        explicit approve()/modify() by the human (agent-memory.md §3)."""
        if rejected:
            return "update_memory rejected by the user; nothing was saved.", "halted"
        if self.deps.memory is None:
            return "update_memory unavailable: agent memory is not configured.", "halted"
        try:
            request = UpdateMemoryInput.model_validate({**hitl["state"], **(updates or {})})
        except ValidationError as exc:
            return f"update_memory not saved: the edited request is invalid ({exc.errors()[0]['msg']}).", "halted"
        try:
            saved = self.deps.memory.save_memory(self._context, request.model_dump())
        except BackendAPIError as exc:
            return f"update_memory not saved: backend returned {exc.status_code} ({exc.detail}).", "halted"
        except Exception:  # noqa: BLE001
            memory_logger.exception("memory: save failed after approval")
            return "update_memory not saved: the memory service is unavailable.", "halted"
        return f"update_memory saved ({saved.get('scope', request.scope)} scope): {request.content}", "done"

    def _maybe_evaluate_rag(self, state: OrchestratorState) -> None:
        """RAG triad sampling (hybrid-document-rag-pipeline.md §4.2) -- only
        for turns that actually consulted documents. Background, fail-open."""
        evaluator = self.deps.rag_evaluator
        if evaluator is None:
            return
        contexts = [e["observation"] for e in state.get("scratchpad") or [] if e["tool"] == DOCUMENT_TOOL_NAME]
        if not contexts:
            return
        question = next((t["content"] for t in reversed(state.get("chat_history") or []) if t["role"] == "user"), "")
        try:
            evaluator.maybe_evaluate(self._context.organization_id, question, contexts, state.get("final_response") or "")
        except Exception:  # noqa: BLE001
            memory_logger.warning("RAG triad sampling failed to dispatch", exc_info=True)

    def _settle(self, result_state: OrchestratorState) -> TurnResult:
        if result_state.get("stage") == "awaiting_approval":
            self.state = result_state
            return TurnResult(status="awaiting_approval", final_response=None, hitl_state=result_state.get("hitl_state"), state=result_state)

        status = "halted" if result_state.get("stage") == "halted" else "done"
        if result_state.get("final_response"):
            # The one place every reply passes before it is saved (agent_messages) or streamed to the UI. Only
            # natural language gets through: a model that printed its raw tool-call syntax as text is cleaned
            # here even if an earlier layer missed it.
            final = result_state.get("final_response") or ""
            cleaned = strip_tool_markup(final)
            if cleaned != final:
                memory_logger.warning("raw tool-call markup removed from the final response")
                result_state = {**result_state, "final_response": cleaned or TOOL_MARKUP_FALLBACK}
            chat_history = list(result_state.get("chat_history") or []) + [
                {"role": "assistant", "content": result_state["final_response"]}
            ]
            result_state = {**result_state, "chat_history": chat_history}
            self._record("assistant", result_state["final_response"])
            self._maybe_evaluate_rag(result_state)

        self.state = result_state
        return TurnResult(status=status, final_response=result_state.get("final_response"), hitl_state=None, state=result_state)
