"""MCP tool catalog for the Maintenance & Parts Inventory Agent.

Thin, RBAC-gated wrappers around the backend's Maintenance/Inventory
endpoints -- see ai_agents/specs/maintenance-inventory-agent.md. Role
gating deliberately keeps two separate write-role sets, neither matching
mcp_server.fuel_tools's (admin, driver) nor foundation_tools's
(admin, fleet_manager): the real backend's write roles for
/api/v1/maintenance are (admin, mechanic) and for /api/v1/inventory are
(admin, fleet_manager) -- each resource has its own real _WRITE_ROLES, and
reusing either existing helper here would silently admit a role the real
backend would 403.

Unlike the other two agents' tool catalogs, reads are gated client-side
too (_READ_ROLES): the spec's driver-refusal edge case covers "any of the
six tools", not just the four writes, since the real backend grants driver
no access to either resource at all -- there's nothing for a driver read to
usefully return.
"""

from __future__ import annotations

from typing import Any

from tools.api_client import call_backend
from tools.auth_context import AgentContext
from tools.schemas import InventoryUpdateInput, MaintenanceLogCreateInput, MechanicReportCreateInput

_READ_ROLES = frozenset({"admin", "fleet_manager", "mechanic"})
_LOG_WRITE_ROLES = frozenset({"admin", "mechanic"})
_INVENTORY_WRITE_ROLES = frozenset({"admin", "fleet_manager"})
# /maintenance/overdue and /maintenance/upcoming are fleet-wide views: the backend
# allows admin and fleet_manager only (its _FLEET_VIEW_ROLES), not mechanics.
_SERVICE_DUE_ROLES = frozenset({"admin", "fleet_manager"})


class PermissionDeniedError(Exception):
    """Raised when the caller's role isn't allowed to invoke a gated tool."""


def _require_role(context: AgentContext, allowed_roles: frozenset[str], tool_name: str) -> None:
    if context.role not in allowed_roles:
        allowed = "/".join(sorted(allowed_roles))
        raise PermissionDeniedError(f"Role '{context.role}' is not permitted to call {tool_name}; requires {allowed}.")


# ---- Maintenance logs ----


def get_maintenance_logs_tool(context: AgentContext) -> list[dict[str, Any]]:
    _require_role(context, _READ_ROLES, "get_maintenance_logs_tool")
    return call_backend("GET", "/api/v1/maintenance", token=context.token)


def create_maintenance_log_tool(context: AgentContext, data: MaintenanceLogCreateInput) -> dict[str, Any]:
    _require_role(context, _LOG_WRITE_ROLES, "create_maintenance_log_tool")
    return call_backend("POST", "/api/v1/maintenance", token=context.token, json=data.model_dump(mode="json"))


def create_mechanic_report_tool(context: AgentContext, log_id: str, data: MechanicReportCreateInput) -> dict[str, Any]:
    _require_role(context, _LOG_WRITE_ROLES, "create_mechanic_report_tool")
    return call_backend(
        "POST", f"/api/v1/maintenance/{log_id}/mechanic-report", token=context.token, json=data.model_dump(mode="json")
    )


# ---- Parts inventory ----


def get_inventory_tool(context: AgentContext) -> list[dict[str, Any]]:
    _require_role(context, _READ_ROLES, "get_inventory_tool")
    return call_backend("GET", "/api/v1/inventory", token=context.token)


def get_low_stock_tool(context: AgentContext) -> list[dict[str, Any]]:
    _require_role(context, _READ_ROLES, "get_low_stock_tool")
    return call_backend("GET", "/api/v1/inventory/low-stock", token=context.token)


def get_service_due_tool(context: AgentContext) -> dict[str, Any]:
    """Vehicles past (overdue) or approaching (upcoming, within 1,000 km) a scheduled
    service, from the compliance rules and logged odometers."""
    _require_role(context, _SERVICE_DUE_ROLES, "get_service_due_tool")
    return {
        "overdue": call_backend("GET", "/api/v1/maintenance/overdue", token=context.token),
        "upcoming": call_backend("GET", "/api/v1/maintenance/upcoming", token=context.token),
    }


def update_inventory_tool(context: AgentContext, part_id: str, data: InventoryUpdateInput) -> dict[str, Any]:
    _require_role(context, _INVENTORY_WRITE_ROLES, "update_inventory_tool")
    return call_backend(
        "PUT", f"/api/v1/inventory/{part_id}", token=context.token, json=data.model_dump(mode="json")
    )
