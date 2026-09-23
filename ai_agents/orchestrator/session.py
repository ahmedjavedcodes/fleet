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

import logging
from dataclasses import dataclass
from typing import Any

from orchestrator.graph import OrchestratorDeps, _format_observation, get_compiled_orchestrator_graph
from orchestrator.security import DEFAULT_SECURITY_CONFIG, SecurityConfig, scan_user_input
from orchestrator.state import OrchestratorState
from tools.auth_context import build_context

logger = logging.getLogger("fleet.security")


@dataclass
class TurnResult:
    status: str  # "done" | "halted" | "awaiting_approval"
    final_response: str | None
    hitl_state: dict[str, Any] | None
    state: OrchestratorState


class OrchestratorSession:
    def __init__(
        self, token: str, *, deps: OrchestratorDeps | None = None, security_config: SecurityConfig = DEFAULT_SECURITY_CONFIG
    ):
        context = build_context(token)
        self.deps = deps or OrchestratorDeps()
        self.security_config = security_config
        self._graph = get_compiled_orchestrator_graph(self.deps)
        self.state: OrchestratorState = {
            "auth_context": {
                "token": token,
                "role": context.role,
                "user_id": context.user_id,
                "organization_id": context.organization_id,
            },
            "chat_history": [],
            "scratchpad": [],
            "active_tool_calls": [],
            "hitl_state": None,
            "final_response": None,
            "hop_count": 0,
            "stage": "planning",
            "halt_reason": None,
        }

    def run(self, message: str, *, image_bytes: bytes | None = None, mime_type: str | None = None) -> TurnResult:
        if self.deps.observer is not None:
            self.deps.observer.start_turn()  # FR 4: a fresh trace_id per session turn

        # Security pre-hook (execution-pre_hooks.md §2): a violation halts
        # BEFORE build_orchestrator_graph is ever invoked -- no LLM call,
        # no state mutation beyond appending the rejected turn to history.
        violation = scan_user_input(message, config=self.security_config)
        if violation is not None:
            logger.warning("Security pre-hook rejected input: %s", violation.reason)
            chat_history = list(self.state.get("chat_history") or []) + [
                {"role": "user", "content": message},
                {"role": "assistant", "content": violation.rejection_message},
            ]
            self.state = {**self.state, "chat_history": chat_history}
            return TurnResult(status="halted", final_response=violation.rejection_message, hitl_state=None, state=self.state)

        chat_history = list(self.state.get("chat_history") or []) + [{"role": "user", "content": message}]
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
        }
        return self._settle(self._graph.invoke(input_state))

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

        if rejected:
            observation = f"{hitl['agent_name']} aborted by the user before the write was made."
            trace_status = "halted"
            raw_result = None
        else:
            result = self.deps.runner.resume(hitl["agent_name"], hitl["thread_id"], updates=updates)
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

    def _settle(self, result_state: OrchestratorState) -> TurnResult:
        if result_state.get("stage") == "awaiting_approval":
            self.state = result_state
            return TurnResult(status="awaiting_approval", final_response=None, hitl_state=result_state.get("hitl_state"), state=result_state)

        status = "halted" if result_state.get("stage") == "halted" else "done"
        if result_state.get("final_response"):
            chat_history = list(result_state.get("chat_history") or []) + [
                {"role": "assistant", "content": result_state["final_response"]}
            ]
            result_state = {**result_state, "chat_history": chat_history}

        self.state = result_state
        return TurnResult(status=status, final_response=result_state.get("final_response"), hitl_state=None, state=result_state)
