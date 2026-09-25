import pytest

from mcp_server import assignment_tools as at
from tools.auth_context import AgentContext
from tools.schemas import AssignmentCreateInput, AssignmentTerminateInput

_ADMIN = AgentContext(token="t", user_id="u1", organization_id="o1", role="admin")
_FLEET_MANAGER = AgentContext(token="t", user_id="u2", organization_id="o1", role="fleet_manager")
_DRIVER = AgentContext(token="t", user_id="u3", organization_id="o1", role="driver")
_MECHANIC = AgentContext(token="t", user_id="u4", organization_id="o1", role="mechanic")

_ASSIGN_INPUT = AssignmentCreateInput(
    driver_id="d1", assigned_at="2026-01-01T08:00:00", start_odometer=1000, take_condition="good"
)
_TERMINATE_INPUT = AssignmentTerminateInput(
    released_at="2026-01-01T17:00:00", end_odometer=1100, leave_condition="good"
)


@pytest.mark.parametrize("context", [_ADMIN, _FLEET_MANAGER])
def test_create_assignment_tool_allows_admin_and_fleet_manager(
    monkeypatch: pytest.MonkeyPatch, context: AgentContext
) -> None:
    monkeypatch.setattr(at, "call_backend", lambda method, path, **kw: (method, path))
    assert at.create_assignment_tool(context, "v1", _ASSIGN_INPUT) == ("POST", "/api/v1/vehicles/v1/assign")


@pytest.mark.parametrize("context", [_DRIVER, _MECHANIC])
def test_create_assignment_tool_refuses_driver_and_mechanic(
    monkeypatch: pytest.MonkeyPatch, context: AgentContext
) -> None:
    monkeypatch.setattr(at, "call_backend", lambda *a, **kw: pytest.fail("backend must not be called"))
    with pytest.raises(at.PermissionDeniedError):
        at.create_assignment_tool(context, "v1", _ASSIGN_INPUT)


@pytest.mark.parametrize("context", [_ADMIN, _FLEET_MANAGER])
def test_terminate_assignment_tool_allows_admin_and_fleet_manager(
    monkeypatch: pytest.MonkeyPatch, context: AgentContext
) -> None:
    monkeypatch.setattr(at, "call_backend", lambda method, path, **kw: (method, path))
    assert at.terminate_assignment_tool(context, "v1", _TERMINATE_INPUT) == ("POST", "/api/v1/vehicles/v1/release")


def test_terminate_assignment_tool_refuses_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(at, "call_backend", lambda *a, **kw: pytest.fail("backend must not be called"))
    with pytest.raises(at.PermissionDeniedError):
        at.terminate_assignment_tool(_DRIVER, "v1", _TERMINATE_INPUT)


@pytest.mark.parametrize("context", [_ADMIN, _FLEET_MANAGER, _DRIVER])
def test_read_tools_allow_admin_fleet_manager_driver(monkeypatch: pytest.MonkeyPatch, context: AgentContext) -> None:
    monkeypatch.setattr(at, "call_backend", lambda method, path, **kw: (method, path))
    assert at.get_driver_assignment_history_tool(context, "d1") == ("GET", "/api/v1/drivers/d1/assignments")
    assert at.get_vehicle_assignment_history_tool(context, "v1") == ("GET", "/api/v1/vehicles/v1/assignments")


def test_read_tools_refuse_mechanic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(at, "call_backend", lambda *a, **kw: pytest.fail("backend must not be called"))
    with pytest.raises(at.PermissionDeniedError):
        at.get_driver_assignment_history_tool(_MECHANIC, "d1")
    with pytest.raises(at.PermissionDeniedError):
        at.get_vehicle_assignment_history_tool(_MECHANIC, "v1")


def test_get_vehicle_assignment_history_tool_passes_target_date(monkeypatch: pytest.MonkeyPatch) -> None:
    import datetime

    captured = {}
    monkeypatch.setattr(at, "call_backend", lambda *a, **kw: captured.update(kw) or [])
    at.get_vehicle_assignment_history_tool(_ADMIN, "v1", target_date=datetime.date(2026, 1, 15))
    assert captured["params"] == {"target_date": "2026-01-15"}
