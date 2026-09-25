"""End-to-end tests for the Assignment Agent's LangGraph orchestration.

Each test is named after the Acceptance Criterion it covers in
ai_agents/specs/assignment-agent.md. RBAC gating, entity resolution, and
backend calls run through the real mcp_server.assignment_tools /
foundation_tools code, with call_backend swapped for an in-memory fake
backend -- same pattern as the other five agents.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from agents.assignment.graph import AssignmentAgentDeps, get_compiled_assignment_graph
from mcp_server import assignment_tools as at
from mcp_server import foundation_tools as vft
from tools.api_client import BackendAPIError


def _token(role: str, org: str = "org-1") -> str:
    payload = {"sub": "user-1", "org": org, "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, "irrelevant-signing-key", algorithm="HS256")


class _FakeBackend:
    def __init__(self) -> None:
        self.vehicles: list[dict] = []
        self.drivers: list[dict] = []
        self.vehicle_history: dict[str, list[dict]] = {}
        self.driver_history: dict[str, dict] = {}
        self.create_calls = 0
        self.terminate_calls = 0
        self.force_409_on_create = False
        self.force_404_on_terminate = False

    def __call__(self, method, path, *, token=None, json=None, params=None, timeout=10.0):
        if method == "GET" and path == "/api/v1/vehicles":
            return list(self.vehicles)
        if method == "GET" and path == "/api/v1/drivers":
            return list(self.drivers)
        if method == "GET" and path.startswith("/api/v1/vehicles/") and path.endswith("/assignments"):
            vehicle_id = path.split("/")[4]
            return list(self.vehicle_history.get(vehicle_id, []))
        if method == "GET" and path.startswith("/api/v1/drivers/") and path.endswith("/assignments"):
            driver_id = path.split("/")[4]
            return self.driver_history.get(driver_id, {"driver_id": driver_id, "current_assignment": None, "total_vehicles_driven": 0, "history": []})

        if method == "POST" and path.endswith("/assign"):
            self.create_calls += 1
            if self.force_409_on_create:
                raise BackendAPIError(409, "Vehicle already has an active assignment")
            vehicle_id = path.split("/")[4]
            record = {"id": "a-new", "vehicle_id": vehicle_id, "released_at": None, **json}
            self.vehicle_history.setdefault(vehicle_id, []).append(record)
            return record

        if method == "POST" and path.endswith("/release"):
            self.terminate_calls += 1
            if self.force_404_on_terminate:
                raise BackendAPIError(404, "No active assignment found for this vehicle")
            vehicle_id = path.split("/")[4]
            history = self.vehicle_history.get(vehicle_id, [])
            for a in history:
                if a["released_at"] is None:
                    a.update(json)
                    return a
            raise AssertionError("no active assignment to release")

        raise AssertionError(f"unexpected backend call: {method} {path}")


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> _FakeBackend:
    fake = _FakeBackend()
    monkeypatch.setattr(at, "call_backend", fake)
    monkeypatch.setattr(vft, "call_backend", fake)
    return fake


def _deps(backend: _FakeBackend, **overrides) -> AssignmentAgentDeps:
    return AssignmentAgentDeps(
        get_vehicles=vft.get_vehicles_tool,
        get_drivers=vft.get_drivers_tool,
        get_driver_history=at.get_driver_assignment_history_tool,
        get_vehicle_history=at.get_vehicle_assignment_history_tool,
        create_assignment=at.create_assignment_tool,
        terminate_assignment=at.terminate_assignment_tool,
        **overrides,
    )


def test_ac1_valid_identifiers_creates_assignment(backend: _FakeBackend) -> None:
    backend.vehicles = [{"id": "v1", "plate_number": "ABC-123"}]
    backend.drivers = [{"id": "d1", "full_name": "Jane Doe"}]
    deps = _deps(backend)
    graph = get_compiled_assignment_graph(deps)

    state = graph.invoke({
        "token": _token("admin"),
        "assign_request": {
            "vehicle_plate": "abc 123", "driver_name": "Jane Doe", "assigned_at": "2026-01-01T08:00:00",
            "start_odometer": 1000, "take_condition": "good",
        },
    })

    assert state["stage"] == "done"
    assert state["created_record"]["driver_id"] == "d1"
    assert backend.create_calls == 1


def test_ac2_terminate_closes_active_assignment(backend: _FakeBackend) -> None:
    backend.vehicles = [{"id": "v1", "plate_number": "ABC-123"}]
    backend.vehicle_history = {"v1": [{"id": "a1", "released_at": None, "start_odometer": 1000}]}
    deps = _deps(backend)
    graph = get_compiled_assignment_graph(deps)

    state = graph.invoke({
        "token": _token("fleet_manager"),
        "terminate_request": {
            "vehicle_plate": "ABC-123", "released_at": "2026-01-01T17:00:00", "end_odometer": 1100,
            "leave_condition": "good",
        },
    })

    assert state["stage"] == "done"
    assert state["created_record"]["released_at"] == "2026-01-01T17:00:00"
    assert backend.terminate_calls == 1


def test_ac3_assigning_occupied_vehicle_halts_with_conflict(backend: _FakeBackend) -> None:
    backend.vehicles = [{"id": "v1", "plate_number": "ABC-123"}]
    backend.drivers = [{"id": "d1", "full_name": "Jane Doe"}]
    backend.vehicle_history = {"v1": [{"id": "a1", "released_at": None}]}
    deps = _deps(backend)
    graph = get_compiled_assignment_graph(deps)

    state = graph.invoke({
        "token": _token("admin"),
        "assign_request": {
            "vehicle_plate": "ABC-123", "driver_name": "Jane Doe", "assigned_at": "2026-01-01T08:00:00",
            "start_odometer": 1000, "take_condition": "good",
        },
    })

    assert state["stage"] == "halted"
    assert "already has an active assignment" in state["halt_reason"]
    assert backend.create_calls == 0


def test_ac3_race_on_create_halts_without_retry(backend: _FakeBackend) -> None:
    backend.vehicles = [{"id": "v1", "plate_number": "ABC-123"}]
    backend.drivers = [{"id": "d1", "full_name": "Jane Doe"}]
    backend.force_409_on_create = True
    deps = _deps(backend)
    graph = get_compiled_assignment_graph(deps)

    state = graph.invoke({
        "token": _token("admin"),
        "assign_request": {
            "vehicle_plate": "ABC-123", "driver_name": "Jane Doe", "assigned_at": "2026-01-01T08:00:00",
            "start_odometer": 1000, "take_condition": "good",
        },
    })

    assert state["stage"] == "halted"
    assert backend.create_calls == 1


@pytest.mark.parametrize("role", ["driver", "mechanic"])
def test_ac4_driver_and_mechanic_refused_before_backend_call(backend: _FakeBackend, role: str) -> None:
    backend.vehicles = [{"id": "v1", "plate_number": "ABC-123"}]
    backend.drivers = [{"id": "d1", "full_name": "Jane Doe"}]
    deps = _deps(backend)
    graph = get_compiled_assignment_graph(deps)

    state = graph.invoke({
        "token": _token(role),
        "assign_request": {
            "vehicle_plate": "ABC-123", "driver_name": "Jane Doe", "assigned_at": "2026-01-01T08:00:00",
            "start_odometer": 1000, "take_condition": "good",
        },
    })

    assert state["stage"] == "halted"
    assert backend.create_calls == 0


@pytest.mark.parametrize("role", ["admin", "fleet_manager"])
def test_ac5_query_returns_history(backend: _FakeBackend, role: str) -> None:
    backend.driver_history = {"d1": {"driver_id": "d1", "current_assignment": None, "total_vehicles_driven": 2, "history": []}}
    backend.vehicle_history = {"v1": [{"id": "a1", "released_at": "2026-01-01T17:00:00"}]}
    deps = _deps(backend)
    graph = get_compiled_assignment_graph(deps)

    driver_state = graph.invoke({"token": _token(role), "query_entity": "driver_history", "query_driver_id": "d1"})
    vehicle_state = graph.invoke({"token": _token(role), "query_entity": "vehicle_history", "query_vehicle_id": "v1"})

    assert driver_state["query_result"] == backend.driver_history["d1"]
    assert vehicle_state["query_result"] == backend.vehicle_history["v1"]


def test_terminate_with_no_active_assignment_halts(backend: _FakeBackend) -> None:
    backend.vehicles = [{"id": "v1", "plate_number": "ABC-123"}]
    backend.vehicle_history = {"v1": [{"id": "a1", "released_at": "2025-01-01T17:00:00"}]}
    deps = _deps(backend)
    graph = get_compiled_assignment_graph(deps)

    state = graph.invoke({
        "token": _token("admin"),
        "terminate_request": {
            "vehicle_plate": "ABC-123", "released_at": "2026-01-01T17:00:00", "end_odometer": 1100,
            "leave_condition": "good",
        },
    })

    assert state["stage"] == "halted"
    assert "no active assignment" in state["halt_reason"].lower()
    assert backend.terminate_calls == 0
