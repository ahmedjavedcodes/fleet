import pytest

from mcp_server import insights_tools as it
from tools.auth_context import AgentContext

_ADMIN = AgentContext(token="t", user_id="u1", organization_id="o1", role="admin")
_FLEET_MANAGER = AgentContext(token="t", user_id="u2", organization_id="o1", role="fleet_manager")
_DRIVER = AgentContext(token="t", user_id="u3", organization_id="o1", role="driver")
_MECHANIC = AgentContext(token="t", user_id="u4", organization_id="o1", role="mechanic")


@pytest.mark.parametrize("context", [_ADMIN, _FLEET_MANAGER])
def test_all_three_tools_allow_admin_and_fleet_manager(monkeypatch: pytest.MonkeyPatch, context: AgentContext) -> None:
    monkeypatch.setattr(it, "call_backend", lambda method, path, **kw: (method, path))
    assert it.get_dashboard_summary_tool(context) == ("GET", "/api/v1/dashboard/summary")
    assert it.get_fleet_health_tool(context) == ("GET", "/api/v1/dashboard/fleet-health")
    assert it.get_fuel_summary_tool(context) == ("GET", "/api/v1/fuel/summary")


@pytest.mark.parametrize("context", [_DRIVER, _MECHANIC])
def test_all_three_tools_refuse_driver_and_mechanic(monkeypatch: pytest.MonkeyPatch, context: AgentContext) -> None:
    monkeypatch.setattr(it, "call_backend", lambda *a, **kw: pytest.fail("backend must not be called"))
    with pytest.raises(it.PermissionDeniedError):
        it.get_dashboard_summary_tool(context)
    with pytest.raises(it.PermissionDeniedError):
        it.get_fleet_health_tool(context)
    with pytest.raises(it.PermissionDeniedError):
        it.get_fuel_summary_tool(context)


def test_get_fuel_summary_tool_passes_month_param(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}
    monkeypatch.setattr(it, "call_backend", lambda *a, **kw: captured.update(kw) or {})
    it.get_fuel_summary_tool(_ADMIN, month="2026-01")
    assert captured["params"] == {"month": "2026-01"}
