"""MCP tool catalog for the Fuel Vision & Leakage Auditor Agent.

Thin, RBAC-gated wrappers around the backend's Fuel/Trip/Dashboard
endpoints -- see ai_agents/specs/fuel-agent.md. Role gating here
deliberately differs from mcp_server/foundation_tools.py's can_write()
(admin/fleet_manager): the real backend's write roles for /api/v1/fuel and
/api/v1/trips are (admin, driver) -- fleet_manager is read-only on both, per
backend/app/api/fuel.py and trips.py's own _WRITE_ROLES. Reusing
auth_context.can_write() here would silently let a fleet_manager through
where the real backend would 403, so this module keeps its own role sets
instead.
"""

from __future__ import annotations

from typing import Any

from tools.api_client import call_backend
from tools.auth_context import AgentContext
from tools.schemas import FuelLogCreateInput, TripLogCreateInput

_LOG_WRITE_ROLES = frozenset({"admin", "driver"})
_TREND_ROLES = frozenset({"admin", "fleet_manager"})


class PermissionDeniedError(Exception):
    """Raised when the caller's role isn't allowed to invoke a gated tool."""


def _require_role(context: AgentContext, allowed_roles: frozenset[str], tool_name: str) -> None:
    if context.role not in allowed_roles:
        allowed = "/".join(sorted(allowed_roles))
        raise PermissionDeniedError(f"Role '{context.role}' is not permitted to call {tool_name}; requires {allowed}.")


# ---- Fuel logs ----


def get_fuel_logs_tool(context: AgentContext) -> list[dict[str, Any]]:
    return call_backend("GET", "/api/v1/fuel", token=context.token)


def create_fuel_log_tool(context: AgentContext, data: FuelLogCreateInput) -> dict[str, Any]:
    _require_role(context, _LOG_WRITE_ROLES, "create_fuel_log_tool")
    return call_backend("POST", "/api/v1/fuel", token=context.token, json=data.model_dump(mode="json"))


# ---- Trip logs ----


def get_trip_logs_tool(context: AgentContext) -> list[dict[str, Any]]:
    return call_backend("GET", "/api/v1/trips", token=context.token)


def create_trip_log_tool(context: AgentContext, data: TripLogCreateInput) -> dict[str, Any]:
    _require_role(context, _LOG_WRITE_ROLES, "create_trip_log_tool")

    # The real /api/v1/trips POST route has no driver-id override for a
    # 'driver'-role caller (unlike /api/v1/fuel, which forces it server
    # side) -- without this, a driver could log a trip under someone else's
    # driver_id. Compensate for that gap here (fuel-agent.md FR 7).
    payload = data.model_dump(mode="json")
    if context.role == "driver":
        payload["driver_id"] = context.user_id

    return call_backend("POST", "/api/v1/trips", token=context.token, json=payload)


# ---- Fuel trends (dashboard analytics) ----


def get_fuel_trends_tool(context: AgentContext, months: int = 12) -> dict[str, Any]:
    _require_role(context, _TREND_ROLES, "get_fuel_trends_tool")
    return call_backend("GET", "/api/v1/dashboard/fuel-trends", token=context.token, params={"months": months})
