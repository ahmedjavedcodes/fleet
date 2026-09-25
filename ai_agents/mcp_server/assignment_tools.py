"""MCP tool catalog for the Driver & Vehicle Assignment Agent.

Thin, RBAC-gated wrappers around the backend's custody endpoints -- see
ai_agents/specs/assignment-agent.md. There is no /api/v1/assignments
resource in the real backend at all: assign/release are vehicle-scoped
(POST /api/v1/vehicles/{vehicle_id}/assign|release, keyed by vehicle_id
because at most one assignment is ever active per vehicle -- "real-time
custody" per root CLAUDE.md), and there is no flat list-all-assignments
endpoint -- reads are always scoped to one driver or one vehicle
(GET /api/v1/drivers/{driver_id}/assignments,
GET /api/v1/vehicles/{vehicle_id}/assignments).

_WRITE_ROLES matches the plan's claim exactly (admin, fleet_manager).
_READ_ROLES additionally permits driver -- a driver reading their own
history is row-restricted server-side (403 on another driver's id); reading
a vehicle's history has no such restriction for any of the three roles.
mechanic is excluded from every tool here, matching the real backend
(absent from all three of its role tuples).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from tools.api_client import call_backend
from tools.auth_context import AgentContext
from tools.schemas import AssignmentCreateInput, AssignmentTerminateInput

_WRITE_ROLES = frozenset({"admin", "fleet_manager"})
_READ_ROLES = frozenset({"admin", "fleet_manager", "driver"})


class PermissionDeniedError(Exception):
    """Raised when the caller's role isn't allowed to invoke a gated tool."""


def _require_role(context: AgentContext, allowed_roles: frozenset[str], tool_name: str) -> None:
    if context.role not in allowed_roles:
        allowed = "/".join(sorted(allowed_roles))
        raise PermissionDeniedError(f"Role '{context.role}' is not permitted to call {tool_name}; requires {allowed}.")


def create_assignment_tool(context: AgentContext, vehicle_id: str, data: AssignmentCreateInput) -> dict[str, Any]:
    _require_role(context, _WRITE_ROLES, "create_assignment_tool")
    return call_backend(
        "POST", f"/api/v1/vehicles/{vehicle_id}/assign", token=context.token, json=data.model_dump(mode="json")
    )


def terminate_assignment_tool(context: AgentContext, vehicle_id: str, data: AssignmentTerminateInput) -> dict[str, Any]:
    _require_role(context, _WRITE_ROLES, "terminate_assignment_tool")
    return call_backend(
        "POST", f"/api/v1/vehicles/{vehicle_id}/release", token=context.token, json=data.model_dump(mode="json")
    )


def get_driver_assignment_history_tool(context: AgentContext, driver_id: str) -> dict[str, Any]:
    _require_role(context, _READ_ROLES, "get_driver_assignment_history_tool")
    return call_backend("GET", f"/api/v1/drivers/{driver_id}/assignments", token=context.token)


def get_vehicle_assignment_history_tool(
    context: AgentContext, vehicle_id: str, target_date: date | None = None
) -> list[dict[str, Any]]:
    _require_role(context, _READ_ROLES, "get_vehicle_assignment_history_tool")
    params = {"target_date": target_date.isoformat()} if target_date else None
    return call_backend("GET", f"/api/v1/vehicles/{vehicle_id}/assignments", token=context.token, params=params)
