"""MCP tool catalog for the Strategic Insights & Executive Dashboard Agent.

Thin, RBAC-gated wrappers around the backend's read-only dashboard/fuel
analytics endpoints -- see ai_agents/specs/strategic-insights-agent.md.

get_fuel_trends_tool is deliberately NOT redefined here -- it already
exists in mcp_server/fuel_tools.py, hitting the exact same endpoint
(GET /api/v1/dashboard/fuel-trends) with the exact same roles this spec
asks for. This module imports and reuses it rather than shipping a second,
functionally-identical tool under the same name.
"""

from __future__ import annotations

from typing import Any

from tools.api_client import call_backend
from tools.auth_context import AgentContext

_INSIGHTS_ROLES = frozenset({"admin", "fleet_manager"})


class PermissionDeniedError(Exception):
    """Raised when the caller's role isn't allowed to invoke a gated tool."""


def _require_role(context: AgentContext, tool_name: str) -> None:
    if context.role not in _INSIGHTS_ROLES:
        raise PermissionDeniedError(f"Role '{context.role}' is not permitted to call {tool_name}; requires admin/fleet_manager.")


def get_dashboard_summary_tool(context: AgentContext) -> dict[str, Any]:
    _require_role(context, "get_dashboard_summary_tool")
    return call_backend("GET", "/api/v1/dashboard/summary", token=context.token)


def get_fleet_health_tool(context: AgentContext) -> list[dict[str, Any]]:
    """Backs the Fleet Health Synthesizer (FR 3). The real backend already
    computes a per-vehicle composite health_score (4 signals, dynamically
    re-normalized) at GET /api/v1/dashboard/fleet-health -- this fetches
    that, it does not recompute health scores from raw records, which the
    original draft's FR 3 wording implied doing from scratch (duplicate,
    possibly-drifting logic, same class of issue as the Fuel Agent's
    is_anomalous handling)."""
    _require_role(context, "get_fleet_health_tool")
    return call_backend("GET", "/api/v1/dashboard/fleet-health", token=context.token)


def get_fuel_summary_tool(context: AgentContext, month: str | None = None) -> dict[str, Any]:
    """Backs the Cross-Domain Cost Correlator (FR 4): the fleet-wide
    dashboard/fuel-trends endpoint has no per-vehicle breakdown ("no
    row-level filtering anywhere -- every number here is fleet-wide by
    definition", per backend/app/api/dashboard.py), so per-vehicle fuel
    cost for a given month comes from GET /api/v1/fuel/summary's
    by_vehicle field instead."""
    _require_role(context, "get_fuel_summary_tool")
    params = {"month": month} if month else None
    return call_backend("GET", "/api/v1/fuel/summary", token=context.token, params=params)
