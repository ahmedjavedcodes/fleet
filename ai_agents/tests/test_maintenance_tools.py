import pytest

from mcp_server import maintenance_tools as mt
from tools.auth_context import AgentContext
from tools.schemas import InventoryUpdateInput, MaintenanceLogCreateInput, MechanicReportCreateInput

_ADMIN = AgentContext(token="t", user_id="u1", organization_id="o1", role="admin")
_FLEET_MANAGER = AgentContext(token="t", user_id="u2", organization_id="o1", role="fleet_manager")
_MECHANIC = AgentContext(token="t", user_id="u3", organization_id="o1", role="mechanic")
_DRIVER = AgentContext(token="t", user_id="u4", organization_id="o1", role="driver")

_LOG_INPUT = MaintenanceLogCreateInput(
    vehicle_id="v1", date="2026-01-01", odometer_at_service=1000, service_type="oil_change"
)
_REPORT_INPUT = MechanicReportCreateInput()
_INVENTORY_INPUT = InventoryUpdateInput(qty_on_hand=10)


@pytest.mark.parametrize("context", [_ADMIN, _FLEET_MANAGER, _MECHANIC])
def test_read_tools_allow_admin_fleet_manager_mechanic(monkeypatch: pytest.MonkeyPatch, context: AgentContext) -> None:
    monkeypatch.setattr(mt, "call_backend", lambda method, path, **kw: (method, path))
    assert mt.get_maintenance_logs_tool(context) == ("GET", "/api/v1/maintenance")
    assert mt.get_inventory_tool(context) == ("GET", "/api/v1/inventory")
    assert mt.get_low_stock_tool(context) == ("GET", "/api/v1/inventory/low-stock")


def test_read_tools_refuse_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mt, "call_backend", lambda *a, **kw: pytest.fail("backend must not be called"))
    with pytest.raises(mt.PermissionDeniedError):
        mt.get_maintenance_logs_tool(_DRIVER)
    with pytest.raises(mt.PermissionDeniedError):
        mt.get_inventory_tool(_DRIVER)
    with pytest.raises(mt.PermissionDeniedError):
        mt.get_low_stock_tool(_DRIVER)


@pytest.mark.parametrize("context", [_ADMIN, _MECHANIC])
def test_create_maintenance_log_tool_allows_admin_and_mechanic(
    monkeypatch: pytest.MonkeyPatch, context: AgentContext
) -> None:
    monkeypatch.setattr(mt, "call_backend", lambda *a, **kw: {"id": "log1"})
    assert mt.create_maintenance_log_tool(context, _LOG_INPUT) == {"id": "log1"}


@pytest.mark.parametrize("context", [_FLEET_MANAGER, _DRIVER])
def test_create_maintenance_log_tool_refuses_fleet_manager_and_driver(
    monkeypatch: pytest.MonkeyPatch, context: AgentContext
) -> None:
    monkeypatch.setattr(mt, "call_backend", lambda *a, **kw: pytest.fail("backend must not be called"))
    with pytest.raises(mt.PermissionDeniedError):
        mt.create_maintenance_log_tool(context, _LOG_INPUT)


@pytest.mark.parametrize("context", [_ADMIN, _MECHANIC])
def test_create_mechanic_report_tool_allows_admin_and_mechanic(
    monkeypatch: pytest.MonkeyPatch, context: AgentContext
) -> None:
    monkeypatch.setattr(mt, "call_backend", lambda *a, **kw: {"id": "r1"})
    assert mt.create_mechanic_report_tool(context, "log1", _REPORT_INPUT) == {"id": "r1"}


def test_create_mechanic_report_tool_refuses_fleet_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mt, "call_backend", lambda *a, **kw: pytest.fail("backend must not be called"))
    with pytest.raises(mt.PermissionDeniedError):
        mt.create_mechanic_report_tool(_FLEET_MANAGER, "log1", _REPORT_INPUT)


@pytest.mark.parametrize("context", [_ADMIN, _FLEET_MANAGER])
def test_update_inventory_tool_allows_admin_and_fleet_manager(
    monkeypatch: pytest.MonkeyPatch, context: AgentContext
) -> None:
    monkeypatch.setattr(mt, "call_backend", lambda *a, **kw: {"id": "p1", "qty_on_hand": 10})
    assert mt.update_inventory_tool(context, "p1", _INVENTORY_INPUT) == {"id": "p1", "qty_on_hand": 10}


@pytest.mark.parametrize("context", [_MECHANIC, _DRIVER])
def test_update_inventory_tool_refuses_mechanic_and_driver(
    monkeypatch: pytest.MonkeyPatch, context: AgentContext
) -> None:
    monkeypatch.setattr(mt, "call_backend", lambda *a, **kw: pytest.fail("backend must not be called"))
    with pytest.raises(mt.PermissionDeniedError):
        mt.update_inventory_tool(context, "p1", _INVENTORY_INPUT)
