"""MCP tool catalog for the Driver Accountability & Asset Misuse Agent.

Thin, RBAC-gated wrappers around the backend's Incidents/Drivers endpoints
-- see ai_agents/specs/driver-accountability-agent.md. Role gating mirrors
what the real routers actually enforce, not what the plan assumed:

- /api/v1/incidents' real _CREATE_READ_ROLES is (admin, fleet_manager,
  driver) for BOTH create and read -- driver reads come back row-filtered
  to their own incidents server-side (backend/app/api/incidents.py's
  _driver_row_filter), they are not blocked outright. mechanic has no
  incidents access at all, so it's the one role gated out here.
- There is no /api/v1/drivers/safety endpoint (the plan guessed at one).
  get_driver_safety_tool instead calls the real
  /api/v1/drivers/{driver_id}/timeline endpoint (_TIMELINE_ROLES: admin,
  fleet_manager, driver) and lets the graph aggregate the incident entries
  it already contains -- see agents/accountability/graph.py.
"""

from __future__ import annotations

from typing import Any

from tools.api_client import call_backend
from tools.auth_context import AgentContext
from tools.schemas import IncidentCreateInput

_INCIDENT_ROLES = frozenset({"admin", "fleet_manager", "driver"})
_TIMELINE_ROLES = frozenset({"admin", "fleet_manager", "driver"})


class PermissionDeniedError(Exception):
    """Raised when the caller's role isn't allowed to invoke a gated tool."""


def _require_role(context: AgentContext, allowed_roles: frozenset[str], tool_name: str) -> None:
    if context.role not in allowed_roles:
        allowed = "/".join(sorted(allowed_roles))
        raise PermissionDeniedError(f"Role '{context.role}' is not permitted to call {tool_name}; requires {allowed}.")


def get_incidents_tool(context: AgentContext) -> list[dict[str, Any]]:
    _require_role(context, _INCIDENT_ROLES, "get_incidents_tool")
    return call_backend("GET", "/api/v1/incidents", token=context.token)


def create_incident_tool(context: AgentContext, data: IncidentCreateInput) -> dict[str, Any]:
    _require_role(context, _INCIDENT_ROLES, "create_incident_tool")
    return call_backend("POST", "/api/v1/incidents", token=context.token, json=data.model_dump(mode="json"))


def get_driver_timeline_tool(context: AgentContext, driver_id: str) -> list[dict[str, Any]]:
    """Backs get_driver_safety_tool's aggregation -- a real backend endpoint,
    unlike the plan's guessed /api/v1/drivers/safety. A driver-role caller
    requesting anyone but their own driver_id gets a 403 from the backend
    itself (get_driver_timeline in backend/app/api/drivers.py)."""
    _require_role(context, _TIMELINE_ROLES, "get_driver_timeline_tool")
    return call_backend("GET", f"/api/v1/drivers/{driver_id}/timeline", token=context.token)
