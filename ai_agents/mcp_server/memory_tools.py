"""Backend-API wrappers for agent memory (/api/v1/memory/*).

No client-side RBAC gating here, unlike the other *_tools modules: who may
write a memory depends on the row's scope and owner, not just the caller's
role, and the backend already enforces exactly that (memory_service's
_SCOPE_WRITE_ROLES + session ownership). A client-side copy of those rules
could only drift.
"""

from __future__ import annotations

from typing import Any

from tools.api_client import call_backend
from tools.auth_context import AgentContext

_PREFIX = "/api/v1/memory"


def create_session_tool(context: AgentContext, *, timeout: float = 10.0) -> dict[str, Any]:
    return call_backend("POST", f"{_PREFIX}/sessions", token=context.token, timeout=timeout)


def get_session_context_tool(context: AgentContext, session_id: str, *, timeout: float = 10.0) -> dict[str, Any]:
    return call_backend("GET", f"{_PREFIX}/sessions/{session_id}/context", token=context.token, timeout=timeout)


def append_message_tool(context: AgentContext, session_id: str, role: str, content: str) -> dict[str, Any]:
    return call_backend(
        "POST", f"{_PREFIX}/sessions/{session_id}/messages", token=context.token, json={"role": role, "content": content}
    )


def apply_summary_tool(
    context: AgentContext, session_id: str, *, message_ids: list[str], running_summary: str, expected_summary_version: int
) -> dict[str, Any]:
    return call_backend(
        "POST",
        f"{_PREFIX}/sessions/{session_id}/summary",
        token=context.token,
        json={
            "message_ids": message_ids,
            "running_summary": running_summary,
            "expected_summary_version": expected_summary_version,
        },
    )


def create_memory_tool(context: AgentContext, payload: dict[str, Any]) -> dict[str, Any]:
    return call_backend("POST", f"{_PREFIX}/memories", token=context.token, json=payload)


def search_memories_tool(context: AgentContext, payload: dict[str, Any], *, timeout: float = 10.0) -> list[dict[str, Any]]:
    return call_backend("POST", f"{_PREFIX}/memories/search", token=context.token, json=payload, timeout=timeout)


def supersede_memories_tool(context: AgentContext, payload: dict[str, Any]) -> dict[str, Any]:
    return call_backend("POST", f"{_PREFIX}/memories/supersede", token=context.token, json=payload)
