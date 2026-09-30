import pytest

from mcp_server import fuel_tools as ft
from tools.auth_context import AgentContext
from tools.schemas import FuelLogCreateInput, TripLogCreateInput

_ADMIN = AgentContext(token="t", user_id="u1", organization_id="o1", role="admin")
_FLEET_MANAGER = AgentContext(token="t", user_id="u2", organization_id="o1", role="fleet_manager")
_DRIVER = AgentContext(token="t", user_id="u3", organization_id="o1", role="driver")
_MECHANIC = AgentContext(token="t", user_id="u4", organization_id="o1", role="mechanic")

_FUEL_INPUT = FuelLogCreateInput(
    vehicle_id="v1", date="2026-01-01", odometer_reading=1000, liters_filled="10", price_per_liter="1.5",
    total_cost="15",
)
_TRIP_INPUT = TripLogCreateInput(
    driver_id="d1", vehicle_id="v1", start_time="2026-01-01T08:00:00", end_time="2026-01-01T09:00:00",
    start_odometer=1000, end_odometer=1050,
)


def test_get_fuel_logs_tool_calls_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ft, "call_backend", lambda method, path, **kw: (method, path))
    assert ft.get_fuel_logs_tool(_ADMIN) == ("GET", "/api/v1/fuel")


def test_get_trip_logs_tool_calls_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ft, "call_backend", lambda method, path, **kw: (method, path))
    assert ft.get_trip_logs_tool(_ADMIN) == ("GET", "/api/v1/trips")


@pytest.mark.parametrize("context", [_ADMIN, _DRIVER])
def test_create_fuel_log_tool_allows_admin_and_driver(monkeypatch: pytest.MonkeyPatch, context: AgentContext) -> None:
    monkeypatch.setattr(ft, "call_backend", lambda *a, **kw: {"id": "f1"})
    assert ft.create_fuel_log_tool(context, _FUEL_INPUT) == {"id": "f1"}


@pytest.mark.parametrize("context", [_FLEET_MANAGER, _MECHANIC])
def test_create_fuel_log_tool_refuses_fleet_manager_and_mechanic(
    monkeypatch: pytest.MonkeyPatch, context: AgentContext
) -> None:
    monkeypatch.setattr(ft, "call_backend", lambda *a, **kw: pytest.fail("backend must not be called"))
    with pytest.raises(ft.PermissionDeniedError):
        ft.create_fuel_log_tool(context, _FUEL_INPUT)


def _backend_with_drivers(captured: dict, drivers: list[dict]):
    def fake(method, path, **kw):
        if method == "GET" and path == "/api/v1/drivers":
            return drivers
        captured.update(kw)
        return {"id": "t1"}

    return fake


@pytest.mark.parametrize("context", [_ADMIN, _DRIVER])
def test_create_trip_log_tool_allows_admin_and_driver(monkeypatch: pytest.MonkeyPatch, context: AgentContext) -> None:
    monkeypatch.setattr(ft, "call_backend", _backend_with_drivers({}, [{"id": "d3", "user_id": _DRIVER.user_id}]))
    assert ft.create_trip_log_tool(context, _TRIP_INPUT) == {"id": "t1"}


def test_create_trip_log_tool_refuses_fleet_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ft, "call_backend", lambda *a, **kw: pytest.fail("backend must not be called"))
    with pytest.raises(ft.PermissionDeniedError):
        ft.create_trip_log_tool(_FLEET_MANAGER, _TRIP_INPUT)


def test_create_trip_log_tool_forces_the_callers_own_driver_profile_id(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    drivers = [{"id": "other-driver", "user_id": "u9"}, {"id": "d3", "user_id": _DRIVER.user_id}]
    monkeypatch.setattr(ft, "call_backend", _backend_with_drivers(captured, drivers))

    other_drivers_trip = TripLogCreateInput(
        driver_id="someone-elses-id", vehicle_id="v1", start_time="2026-01-01T08:00:00",
        end_time="2026-01-01T09:00:00", start_odometer=1000, end_odometer=1050,
    )
    ft.create_trip_log_tool(_DRIVER, other_drivers_trip)

    # Driver.id, not the JWT's User.id: trip_logs.driver_id references drivers.id.
    assert captured["json"]["driver_id"] == "d3"


def test_create_trip_log_tool_refuses_a_driver_with_no_linked_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(ft, "call_backend", _backend_with_drivers(captured, [{"id": "x", "user_id": "someone-else"}]))
    with pytest.raises(ft.PermissionDeniedError):
        ft.create_trip_log_tool(_DRIVER, _TRIP_INPUT)
    assert captured == {}  # nothing was posted


def test_create_trip_log_tool_sends_fuel_consumed_in_liters(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(ft, "call_backend", _backend_with_drivers(captured, []))
    ft.create_trip_log_tool(_ADMIN, _TRIP_INPUT.model_copy(update={"fuel_consumed": "32.5"}))
    assert captured["json"]["fuel_consumed"] == "32.5"


def test_trip_input_rejects_negative_fuel_consumed() -> None:
    with pytest.raises(ValueError):
        TripLogCreateInput(**{**_TRIP_INPUT.model_dump(), "fuel_consumed": "-1"})


def test_create_trip_log_tool_does_not_override_driver_id_for_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}
    monkeypatch.setattr(ft, "call_backend", lambda *a, **kw: captured.update(kw) or {"id": "t1"})

    ft.create_trip_log_tool(_ADMIN, _TRIP_INPUT)

    assert captured["json"]["driver_id"] == "d1"


@pytest.mark.parametrize("context", [_ADMIN, _FLEET_MANAGER])
def test_get_fuel_trends_tool_allows_admin_and_fleet_manager(
    monkeypatch: pytest.MonkeyPatch, context: AgentContext
) -> None:
    monkeypatch.setattr(ft, "call_backend", lambda *a, **kw: {"months": 12})
    assert ft.get_fuel_trends_tool(context) == {"months": 12}


@pytest.mark.parametrize("context", [_DRIVER, _MECHANIC])
def test_get_fuel_trends_tool_refuses_driver_and_mechanic(
    monkeypatch: pytest.MonkeyPatch, context: AgentContext
) -> None:
    monkeypatch.setattr(ft, "call_backend", lambda *a, **kw: pytest.fail("backend must not be called"))
    with pytest.raises(ft.PermissionDeniedError):
        ft.get_fuel_trends_tool(context)
