"""End-to-end tests for the Strategic Insights Agent's LangGraph
orchestration.

Each test is named after the Acceptance Criterion it covers in
ai_agents/specs/strategic-insights-agent.md. RBAC gating and backend calls
run through the real mcp_server.insights_tools / fuel_tools /
maintenance_tools code, with call_backend swapped for an in-memory fake
backend -- same pattern as the other four agents. This agent has no
extraction skill to fake -- it's pure read/synthesis, nothing to mock but
the backend.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from agents.insights.graph import InsightsAgentDeps, get_compiled_insights_graph
from mcp_server import fuel_tools as ft
from mcp_server import insights_tools as it
from mcp_server import maintenance_tools as mt
from tools.api_client import BackendAPIError


def _token(role: str, org: str = "org-1") -> str:
    payload = {"sub": "user-1", "org": org, "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, "irrelevant-signing-key", algorithm="HS256")


class _FakeBackend:
    def __init__(self) -> None:
        self.dashboard_summary: dict = {}
        self.fuel_trends: list = []
        self.fleet_health: list = []
        self.fuel_summary: dict = {"by_vehicle": []}
        self.maintenance_logs: list = []
        self.fail_next = False

    def __call__(self, method, path, *, token=None, json=None, params=None, timeout=10.0):
        if self.fail_next:
            raise BackendAPIError(503, "Service Unavailable")
        if method == "GET" and path == "/api/v1/dashboard/summary":
            return self.dashboard_summary
        if method == "GET" and path == "/api/v1/dashboard/fuel-trends":
            return self.fuel_trends
        if method == "GET" and path == "/api/v1/dashboard/fleet-health":
            return self.fleet_health
        if method == "GET" and path == "/api/v1/fuel/summary":
            return self.fuel_summary
        if method == "GET" and path == "/api/v1/maintenance":
            return self.maintenance_logs

        raise AssertionError(f"unexpected backend call: {method} {path}")


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> _FakeBackend:
    fake = _FakeBackend()
    monkeypatch.setattr(it, "call_backend", fake)
    monkeypatch.setattr(ft, "call_backend", fake)
    monkeypatch.setattr(mt, "call_backend", fake)
    return fake


def _deps(backend: _FakeBackend) -> InsightsAgentDeps:
    return InsightsAgentDeps(
        get_dashboard_summary=it.get_dashboard_summary_tool,
        get_fleet_health=it.get_fleet_health_tool,
        get_fuel_trends=ft.get_fuel_trends_tool,
        get_fuel_summary=it.get_fuel_summary_tool,
        get_maintenance_logs=mt.get_maintenance_logs_tool,
    )


def test_ac1_executive_summary_fetches_and_synthesizes(backend: _FakeBackend) -> None:
    backend.dashboard_summary = {"total_vehicles": 10, "open_incidents_count": 2}
    backend.fuel_trends = [{"month": "2026-01", "total_cost": "500"}]
    backend.fleet_health = [{"vehicle_id": "v1", "health_score": 80}, {"vehicle_id": "v2", "health_score": 40}]
    deps = _deps(backend)
    graph = get_compiled_insights_graph(deps)

    state = graph.invoke({"token": _token("admin"), "request_type": "executive_summary"})

    assert state["stage"] == "done"
    assert state["dashboard_summary"] == backend.dashboard_summary
    assert state["fuel_trends"] == backend.fuel_trends
    assert state["fleet_health"]["average_health_score"] == 60.0
    assert state["fleet_health"]["at_risk_count"] == 1


def test_ac2_cost_analysis_correlates_per_vehicle(backend: _FakeBackend) -> None:
    backend.fuel_summary = {"by_vehicle": [{"vehicle_id": "v1", "total_cost": "300"}]}
    backend.maintenance_logs = [{"vehicle_id": "v1", "cost": "700"}, {"vehicle_id": "v2", "cost": "50"}]
    deps = _deps(backend)
    graph = get_compiled_insights_graph(deps)

    state = graph.invoke({"token": _token("fleet_manager"), "request_type": "cost_analysis"})

    assert state["stage"] == "done"
    by_id = {r["vehicle_id"]: r for r in state["cost_correlation"]}
    assert by_id["v1"]["total_cost"] == 1000.0
    assert by_id["v2"]["total_cost"] == 50.0
    assert state["cost_correlation"][0]["vehicle_id"] == "v1"  # sorted descending


@pytest.mark.parametrize("role", ["driver", "mechanic"])
def test_ac3_driver_and_mechanic_refused_before_any_backend_call(backend: _FakeBackend, role: str) -> None:
    deps = _deps(backend)
    graph = get_compiled_insights_graph(deps)

    for request in [
        {"request_type": "executive_summary"},
        {"request_type": "cost_analysis"},
        {"query_entity": "fuel_trends"},
    ]:
        state = graph.invoke({"token": _token(role), **request})
        assert state["stage"] == "halted"
        assert "permit" in state["halt_reason"].lower()


def test_ac4_query_fuel_trends_returns_data(backend: _FakeBackend) -> None:
    backend.fuel_trends = [{"month": "2026-01", "total_cost": "500", "avg_cost_per_km": "1.2"}]
    deps = _deps(backend)
    graph = get_compiled_insights_graph(deps)

    state = graph.invoke({"token": _token("admin"), "query_entity": "fuel_trends"})

    assert state["stage"] == "done"
    assert state["query_result"] == backend.fuel_trends


def test_empty_fleet_health_does_not_crash_synthesis(backend: _FakeBackend) -> None:
    deps = _deps(backend)
    graph = get_compiled_insights_graph(deps)

    state = graph.invoke({"token": _token("admin"), "request_type": "executive_summary"})

    assert state["stage"] == "done"
    assert state["fleet_health"]["average_health_score"] is None
    assert state["fleet_health"]["at_risk_count"] == 0


def test_backend_failure_during_aggregation_halts_with_clean_reason(backend: _FakeBackend) -> None:
    backend.fail_next = True
    deps = _deps(backend)
    graph = get_compiled_insights_graph(deps)

    state = graph.invoke({"token": _token("admin"), "request_type": "executive_summary"})

    assert state["stage"] == "halted"
    assert "503" in state["halt_reason"]
