import pytest

from mcp_server import foundation_tools as ft
from tools.auth_context import AgentContext
from tools.schemas import DriverCreateInput, SupplierCreateInput, VehicleCreateInput

_ADMIN = AgentContext(token="t", user_id="u1", organization_id="o1", role="admin")
_DRIVER = AgentContext(token="t", user_id="u2", organization_id="o1", role="driver")
_MECHANIC = AgentContext(token="t", user_id="u3", organization_id="o1", role="mechanic")


def test_get_vehicles_tool_calls_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(ft, "call_backend", lambda *a, **kw: calls.append((a, kw)) or [{"id": "v1"}])

    result = ft.get_vehicles_tool(_ADMIN)

    assert result == [{"id": "v1"}]
    assert calls[0][0] == ("GET", "/api/v1/vehicles")
    assert calls[0][1]["token"] == "t"


def test_create_vehicle_tool_sends_bridged_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(ft, "call_backend", lambda *a, **kw: calls.append((a, kw)) or {"id": "v-new"})

    data = VehicleCreateInput(plate_number="ABC-123", make="Ford", model="F150", year=2020, vin="1HG", fuel_type="diesel")
    result = ft.create_vehicle_tool(_ADMIN, data)

    assert result == {"id": "v-new"}
    assert calls[0][0] == ("POST", "/api/v1/vehicles")
    assert calls[0][1]["json"]["plate_number"] == "ABC-123"
    assert calls[0][1]["json"]["fuel_type"] == "diesel"


@pytest.mark.parametrize("context", [_DRIVER, _MECHANIC])
def test_create_vehicle_tool_refuses_non_write_roles(monkeypatch: pytest.MonkeyPatch, context: AgentContext) -> None:
    monkeypatch.setattr(ft, "call_backend", lambda *a, **kw: pytest.fail("backend must not be called"))

    data = VehicleCreateInput(plate_number="ABC-123", make="Ford", model="F150", year=2020, vin="1HG", fuel_type="diesel")
    with pytest.raises(ft.PermissionDeniedError):
        ft.create_vehicle_tool(context, data)


def test_create_driver_tool_refuses_driver_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ft, "call_backend", lambda *a, **kw: pytest.fail("backend must not be called"))

    data = DriverCreateInput(full_name="Jane Doe", license_number="DL1", license_expiry="2030-01-01", phone="+1555")
    with pytest.raises(ft.PermissionDeniedError):
        ft.create_driver_tool(_DRIVER, data)


def test_create_supplier_tool_allows_fleet_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ft, "call_backend", lambda *a, **kw: {"id": "s1"})
    manager = AgentContext(token="t", user_id="u4", organization_id="o1", role="fleet_manager")

    result = ft.create_supplier_tool(manager, SupplierCreateInput(name="Acme Parts"))
    assert result == {"id": "s1"}


def test_get_drivers_and_suppliers_tools_call_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ft, "call_backend", lambda method, path, **kw: (method, path))
    assert ft.get_drivers_tool(_ADMIN) == ("GET", "/api/v1/drivers")
    assert ft.get_suppliers_tool(_ADMIN) == ("GET", "/api/v1/suppliers")
