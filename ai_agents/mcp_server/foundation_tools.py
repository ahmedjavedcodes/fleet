"""MCP tool catalog for the Fleet Registry Agent (Spec 00 onboarding).

Thin, RBAC-gated wrappers around the backend's Vehicles/Drivers/Suppliers
endpoints -- see ai_agents/specs/fleet-registry-agent.md for the full spec.
Every write tool checks tools.auth_context.can_write before making any
backend call (Acceptance Criterion 6); the backend independently re-checks
the caller's live role and returns 403 on the same violation, so this is a
fail-fast layer, not the security boundary itself.

Lives in ai_agents/mcp_server/ (not ai_agents/mcp/) deliberately: the latter
shadows the installed `mcp` SDK package on sys.path (see the NOTE in
ai_agents/mcp/server.py) -- this module avoids that collision entirely
since it has no dependency on the mcp SDK at all.

Note: the backend's list endpoints (GET /vehicles, /drivers, /suppliers)
take no filter query params today -- filtering (by plate, status, etc.) is
client-side until the backend adds them.
"""

from __future__ import annotations

from typing import Any

from tools.api_client import call_backend
from tools.auth_context import AgentContext, can_write
from tools.schemas import DriverCreateInput, SupplierCreateInput, VehicleCreateInput


class PermissionDeniedError(Exception):
    """Raised when the caller's role isn't allowed to invoke a create_*_tool."""


def _require_write(context: AgentContext, tool_name: str) -> None:
    if not can_write(context):
        raise PermissionDeniedError(
            f"Role '{context.role}' is not permitted to call {tool_name}; requires admin or fleet_manager."
        )


# ---- Vehicles ----


def get_vehicles_tool(context: AgentContext) -> list[dict[str, Any]]:
    return call_backend("GET", "/api/v1/vehicles", token=context.token)


def create_vehicle_tool(context: AgentContext, data: VehicleCreateInput) -> dict[str, Any]:
    _require_write(context, "create_vehicle_tool")
    return call_backend("POST", "/api/v1/vehicles", token=context.token, json=data.model_dump(mode="json"))


# ---- Drivers ----


def get_drivers_tool(context: AgentContext) -> list[dict[str, Any]]:
    return call_backend("GET", "/api/v1/drivers", token=context.token)


def create_driver_tool(context: AgentContext, data: DriverCreateInput) -> dict[str, Any]:
    _require_write(context, "create_driver_tool")
    return call_backend("POST", "/api/v1/drivers", token=context.token, json=data.model_dump(mode="json"))


# ---- Suppliers ----


def get_suppliers_tool(context: AgentContext) -> list[dict[str, Any]]:
    return call_backend("GET", "/api/v1/suppliers", token=context.token)


def create_supplier_tool(context: AgentContext, data: SupplierCreateInput) -> dict[str, Any]:
    _require_write(context, "create_supplier_tool")
    return call_backend("POST", "/api/v1/suppliers", token=context.token, json=data.model_dump(mode="json"))
