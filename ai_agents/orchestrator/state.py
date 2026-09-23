"""LangGraph state schema for the Grand Orchestrator.

Mirrors grand-orchestrator.md section 3's Master State fields exactly:
auth_context, chat_history, scratchpad, active_tool_calls, hitl_state,
final_response.

auth_context is populated once, at session start, from the caller's own
JWT (mirroring every sub-agent's inject_context) -- FR 2's "Immutable RBAC
Injection": the routing LLM only ever sees tool names/descriptions/schemas,
never auth_context itself, so it has no channel through which to forge or
override the caller's role or org.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

Stage = Literal["planning", "awaiting_approval", "done", "halted"]


class ScratchpadEntry(TypedDict):
    hop: int
    tool: str
    args: dict[str, Any]
    observation: str


class HitlState(TypedDict, total=False):
    agent_name: str
    thread_id: str
    tool_name: str
    pending_node: str
    state: dict[str, Any]  # the paused sub-agent's own state, for the frontend to render


class OrchestratorState(TypedDict, total=False):
    auth_context: dict[str, str]  # {token, role, user_id, organization_id} -- LLM never sees this
    chat_history: list[dict[str, str]]  # [{"role": "user"|"assistant", "content": ...}, ...]
    scratchpad: list[ScratchpadEntry]
    active_tool_calls: list[dict[str, Any]]  # the LLM's tool_calls for the current hop
    hitl_state: HitlState | None
    final_response: str | None

    # bookkeeping not named in the spec's state list but required to run
    # the loop safely. LangGraph only merges keys declared in this TypedDict
    # -- an undeclared key returned from a node is silently dropped on the
    # next hop, not an error, so everything a node writes must be listed
    # here even when it's "private" bookkeeping.
    hop_count: int
    stage: Stage
    halt_reason: str | None
    _tool_retry_counts: dict[str, int]
    _pending_image_bytes: bytes | None
    _pending_mime_type: str | None
    _fact_check_retries: int
    _fact_check_warning: str | None
