"""End-to-end tests for the Fuel Agent's LangGraph orchestration.

Each test is named after the Acceptance Criterion it covers in
ai_agents/specs/fuel-agent.md. Only vision extraction is faked (no live
Groq call); RBAC gating, the odometer-continuity guardrail, field bridging,
and backend calls all run through the real mcp_server.fuel_tools /
mcp_server.foundation_tools code, with call_backend swapped for an
in-memory fake backend -- same pattern as test_foundation_graph.py.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from agents.fuel.graph import FuelAgentDeps, get_compiled_fuel_graph
from mcp_server import foundation_tools as vft
from mcp_server import fuel_tools as ft
from tools.file_parsers import ExtractionFailedError
from tools.schemas import FuelReceiptExtraction


def _token(role: str, org: str = "org-1", sub: str = "user-1") -> str:
    payload = {"sub": sub, "org": org, "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, "irrelevant-signing-key", algorithm="HS256")


class _FakeBackend:
    """In-memory stand-in for call_backend, shared by fuel_tools and foundation_tools."""

    def __init__(self) -> None:
        self.vehicles: list[dict] = []
        self.fuel_logs: list[dict] = []
        self.trip_logs: list[dict] = []
        self.fuel_trends = {"months": []}
        self.create_fuel_calls = 0
        self.create_trip_calls = 0
        self.next_fuel_log_is_anomalous = False

    def __call__(self, method, path, *, token=None, json=None, params=None, timeout=10.0):
        if method == "GET" and path == "/api/v1/vehicles":
            return list(self.vehicles)
        if method == "GET" and path == "/api/v1/fuel":
            return list(self.fuel_logs)
        if method == "GET" and path == "/api/v1/trips":
            return list(self.trip_logs)
        if method == "GET" and path == "/api/v1/dashboard/fuel-trends":
            return self.fuel_trends

        if method == "POST" and path == "/api/v1/fuel":
            self.create_fuel_calls += 1
            cost_per_km = None
            record = {
                "id": "f-new", **json, "cost_per_km": cost_per_km, "is_anomalous": self.next_fuel_log_is_anomalous,
            }
            self.fuel_logs.append(record)
            # advance the vehicle's odometer like the real backend does
            for v in self.vehicles:
                if v["id"] == json["vehicle_id"] and json["odometer_reading"] > v["current_odometer"]:
                    v["current_odometer"] = json["odometer_reading"]
            return record

        if method == "POST" and path == "/api/v1/trips":
            self.create_trip_calls += 1
            record = {"id": "t-new", **json}
            self.trip_logs.append(record)
            return record

        raise AssertionError(f"unexpected backend call: {method} {path}")


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> _FakeBackend:
    fake = _FakeBackend()
    monkeypatch.setattr(ft, "call_backend", fake)
    monkeypatch.setattr(vft, "call_backend", fake)
    return fake


def _deps(backend: _FakeBackend, **overrides) -> FuelAgentDeps:
    return FuelAgentDeps(
        get_vehicles=vft.get_vehicles_tool,
        get_fuel_logs=ft.get_fuel_logs_tool,
        get_trip_logs=ft.get_trip_logs_tool,
        get_fuel_trends=ft.get_fuel_trends_tool,
        create_fuel_log=ft.create_fuel_log_tool,
        create_trip_log=ft.create_trip_log_tool,
        **overrides,
    )


def test_ac1_valid_receipt_creates_fuel_log(backend: _FakeBackend) -> None:
    backend.vehicles = [{"id": "v1", "plate_number": "ABC-123", "current_odometer": 1000}]
    extraction = FuelReceiptExtraction(
        station_name="Shell", receipt_date="2026-01-05", liters=10.0, total_cost=15.0, odometer=1050,
        plate_number="abc 123",
    )
    deps = _deps(backend, extract_receipt=lambda img, mime: extraction)
    graph = get_compiled_fuel_graph(deps)

    state = graph.invoke({"token": _token("admin"), "image_bytes": b"jpeg", "mime_type": "image/jpeg"})

    assert state["stage"] == "done"
    assert state["created_record"]["vehicle_id"] == "v1"
    assert state["created_record"]["price_per_liter"] == "1.5000"
    assert backend.create_fuel_calls == 1


def test_ac2_odometer_not_advancing_halts_before_create(backend: _FakeBackend) -> None:
    backend.vehicles = [{"id": "v1", "plate_number": "ABC-123", "current_odometer": 2000}]
    extraction = FuelReceiptExtraction(
        station_name="Shell", receipt_date="2026-01-05", liters=10.0, total_cost=15.0, odometer=1500,
        plate_number="ABC-123",
    )
    deps = _deps(backend, extract_receipt=lambda img, mime: extraction)
    graph = get_compiled_fuel_graph(deps)

    state = graph.invoke({"token": _token("admin"), "image_bytes": b"jpeg", "mime_type": "image/jpeg"})

    assert state["stage"] == "halted"
    assert "odometer" in state["halt_reason"].lower()
    assert backend.create_fuel_calls == 0


def test_ac3_unknown_plate_halts(backend: _FakeBackend) -> None:
    backend.vehicles = [{"id": "v1", "plate_number": "ABC-123", "current_odometer": 1000}]
    extraction = FuelReceiptExtraction(
        station_name="Shell", receipt_date="2026-01-05", liters=10.0, total_cost=15.0, odometer=1050,
        plate_number="ZZZ-999",
    )
    deps = _deps(backend, extract_receipt=lambda img, mime: extraction)
    graph = get_compiled_fuel_graph(deps)

    state = graph.invoke({"token": _token("admin"), "image_bytes": b"jpeg", "mime_type": "image/jpeg"})

    assert state["stage"] == "halted"
    assert "no vehicle" in state["halt_reason"].lower()
    assert backend.create_fuel_calls == 0


def test_ac4_unreadable_receipt_halts_without_creating(backend: _FakeBackend) -> None:
    def failing_extractor(img, mime):
        raise ExtractionFailedError("could not read the fuel receipt")

    deps = _deps(backend, extract_receipt=failing_extractor)
    graph = get_compiled_fuel_graph(deps)

    state = graph.invoke({"token": _token("admin"), "image_bytes": b"blurry", "mime_type": "image/jpeg"})

    assert state["stage"] == "halted"
    assert backend.create_fuel_calls == 0


def test_ac5_anomalous_flag_surfaced_from_backend_response(backend: _FakeBackend) -> None:
    backend.vehicles = [{"id": "v1", "plate_number": "ABC-123", "current_odometer": 1000}]
    backend.next_fuel_log_is_anomalous = True
    extraction = FuelReceiptExtraction(
        station_name="Shell", receipt_date="2026-01-05", liters=10.0, total_cost=90.0, odometer=1050,
        plate_number="ABC-123",
    )
    deps = _deps(backend, extract_receipt=lambda img, mime: extraction)
    graph = get_compiled_fuel_graph(deps)

    state = graph.invoke({"token": _token("admin"), "image_bytes": b"jpeg", "mime_type": "image/jpeg"})

    assert state["stage"] == "done"
    assert state["created_record"]["is_anomalous"] is True


def test_ac6_fleet_manager_refused_before_backend_create(backend: _FakeBackend) -> None:
    deps = _deps(backend)
    graph = get_compiled_fuel_graph(deps)

    trip_fields = {
        "driver_id": "d1", "vehicle_id": "v1", "start_time": "2026-01-01T08:00:00",
        "end_time": "2026-01-01T09:00:00", "start_odometer": 1000, "end_odometer": 1050,
    }
    state = graph.invoke({"token": _token("fleet_manager"), "trip_fields": trip_fields})

    assert state["stage"] == "halted"
    assert "permit" in state["halt_reason"].lower()
    assert backend.create_trip_calls == 0


def test_ac7_driver_trip_log_driver_id_overridden(backend: _FakeBackend) -> None:
    deps = _deps(backend)
    graph = get_compiled_fuel_graph(deps)

    trip_fields = {
        "driver_id": "someone-elses-id", "vehicle_id": "v1", "start_time": "2026-01-01T08:00:00",
        "end_time": "2026-01-01T09:00:00", "start_odometer": 1000, "end_odometer": 1050,
    }
    state = graph.invoke({"token": _token("driver", sub="driver-self-id"), "trip_fields": trip_fields})

    assert state["stage"] == "done"
    assert state["created_record"]["driver_id"] == "driver-self-id"
    assert backend.create_trip_calls == 1


@pytest.mark.parametrize("role", ["admin", "fleet_manager", "driver"])
def test_ac8_read_queries_return_results_for_permitted_roles(backend: _FakeBackend, role: str) -> None:
    backend.fuel_logs = [{"id": "f1"}]
    backend.trip_logs = [{"id": "t1"}]
    deps = _deps(backend)
    graph = get_compiled_fuel_graph(deps)

    fuel_state = graph.invoke({"token": _token(role), "query_entity": "fuel_logs"})
    trip_state = graph.invoke({"token": _token(role), "query_entity": "trip_logs"})

    assert fuel_state["query_result"] == backend.fuel_logs
    assert trip_state["query_result"] == backend.trip_logs


@pytest.mark.parametrize("role,allowed", [("admin", True), ("fleet_manager", True), ("driver", False), ("mechanic", False)])
def test_ac9_fuel_trends_gated_to_admin_and_fleet_manager(backend: _FakeBackend, role: str, allowed: bool) -> None:
    backend.fuel_trends = {"months": ["2026-01"]}
    deps = _deps(backend)
    graph = get_compiled_fuel_graph(deps)

    state = graph.invoke({"token": _token(role), "query_entity": "fuel_trends"})

    if allowed:
        assert state["stage"] == "done"
        assert state["query_result"] == backend.fuel_trends
    else:
        assert state["stage"] == "halted"
        assert "permit" in state["halt_reason"].lower()
