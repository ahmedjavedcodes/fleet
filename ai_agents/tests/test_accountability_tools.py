import pytest

from mcp_server import accountability_tools as at
from tools.auth_context import AgentContext
from tools.schemas import IncidentCreateInput

_ADMIN = AgentContext(token="t", user_id="u1", organization_id="o1", role="admin")
_FLEET_MANAGER = AgentContext(token="t", user_id="u2", organization_id="o1", role="fleet_manager")
_DRIVER = AgentContext(token="t", user_id="u3", organization_id="o1", role="driver")
_MECHANIC = AgentContext(token="t", user_id="u4", organization_id="o1", role="mechanic")

_INCIDENT_INPUT = IncidentCreateInput(
    vehicle_id="v1", incident_type="damage", date="2026-01-01", severity="minor", description="Scratch"
)


@pytest.mark.parametrize("context", [_ADMIN, _FLEET_MANAGER, _DRIVER])
def test_get_incidents_tool_allows_admin_fleet_manager_driver(
    monkeypatch: pytest.MonkeyPatch, context: AgentContext
) -> None:
    monkeypatch.setattr(at, "call_backend", lambda method, path, **kw: (method, path))
    assert at.get_incidents_tool(context) == ("GET", "/api/v1/incidents")


def test_get_incidents_tool_refuses_mechanic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(at, "call_backend", lambda *a, **kw: pytest.fail("backend must not be called"))
    with pytest.raises(at.PermissionDeniedError):
        at.get_incidents_tool(_MECHANIC)


@pytest.mark.parametrize("context", [_ADMIN, _FLEET_MANAGER, _DRIVER])
def test_create_incident_tool_allows_admin_fleet_manager_driver(
    monkeypatch: pytest.MonkeyPatch, context: AgentContext
) -> None:
    monkeypatch.setattr(at, "call_backend", lambda *a, **kw: {"id": "i1"})
    assert at.create_incident_tool(context, _INCIDENT_INPUT) == {"id": "i1"}


def test_create_incident_tool_refuses_mechanic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(at, "call_backend", lambda *a, **kw: pytest.fail("backend must not be called"))
    with pytest.raises(at.PermissionDeniedError):
        at.create_incident_tool(_MECHANIC, _INCIDENT_INPUT)


@pytest.mark.parametrize("context", [_ADMIN, _FLEET_MANAGER, _DRIVER])
def test_get_driver_timeline_tool_allows_admin_fleet_manager_driver(
    monkeypatch: pytest.MonkeyPatch, context: AgentContext
) -> None:
    monkeypatch.setattr(at, "call_backend", lambda method, path, **kw: (method, path))
    assert at.get_driver_timeline_tool(context, "d1") == ("GET", "/api/v1/drivers/d1/timeline")


def test_get_driver_timeline_tool_refuses_mechanic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(at, "call_backend", lambda *a, **kw: pytest.fail("backend must not be called"))
    with pytest.raises(at.PermissionDeniedError):
        at.get_driver_timeline_tool(_MECHANIC, "d1")
