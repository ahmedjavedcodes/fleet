"""End-to-end tests for the Fuel Agent's LangGraph orchestration.

Each test is named after the Acceptance Criterion it covers in
ai_agents/specs/fuel-agent.md. Only vision extraction is faked (no live
Groq call); RBAC gating, the odometer-continuity guardrail, field bridging,
and backend calls all run through the real mcp_server.fuel_tools /
mcp_server.foundation_tools code, with call_backend swapped for an
in-memory fake backend -- same pattern as test_foundation_graph.py.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

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
        self.drivers: list[dict] = []
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
        if method == "GET" and path == "/api/v1/drivers":
            return list(self.drivers)

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
    backend.drivers = [{"id": "driver-profile-id", "user_id": "driver-self-id"}]
    state = graph.invoke({"token": _token("driver", sub="driver-self-id"), "trip_fields": trip_fields})

    assert state["stage"] == "done"
    # The caller's Driver.id (resolved from their User.id), never the JWT sub itself.
    assert state["created_record"]["driver_id"] == "driver-profile-id"
    assert backend.create_trip_calls == 1


def test_trip_log_carries_fuel_consumed_and_rejects_a_bad_key(backend: _FakeBackend) -> None:
    graph = get_compiled_fuel_graph(_deps(backend))
    trip_fields = {
        "driver_id": "d1", "vehicle_id": "v1", "start_time": "2026-01-01T08:00:00",
        "end_time": "2026-01-01T09:00:00", "start_odometer": 1000, "end_odometer": 1050, "fuel_consumed": 32.5,
    }
    state = graph.invoke({"token": _token("admin"), "trip_fields": trip_fields})
    assert state["stage"] == "done"
    assert state["created_record"]["fuel_consumed"] == "32.5"

    bad = graph.invoke({"token": _token("admin"), "trip_fields": {**trip_fields, "fuel_litres": 3}})
    assert bad["stage"] == "halted"
    assert "Invalid trip_fields" in bad["halt_reason"]
    assert backend.create_trip_calls == 1  # the bad call never reached the backend


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


# ---- receipt photo + what the user says in chat ---------------------------------------------------
# "Log this fuel fill for AB-1234. The total was 50 liters at Rs 280/L." with a photo of a receipt that shows
# another plate and other figures: the user's words win, as the tool schema promises.


def _photo_run(backend: _FakeBackend, stated: dict | None, **receipt) -> dict:
    backend.vehicles = [
        {"id": "v1", "plate_number": "AB-1234", "current_odometer": 1000},
        {"id": "v2", "plate_number": "LB-7967", "current_odometer": 500},
    ]
    fields = {"station_name": "Mehar Petroleum", "receipt_date": "2026-09-24", "liters": 39.2, "total_cost": 15365.0,
              "odometer": 1200, "plate_number": "LB-7967", **receipt}
    deps = _deps(backend, extract_receipt=lambda img, mime: FuelReceiptExtraction(**fields))
    state = {"token": _token("admin"), "image_bytes": b"jpeg", "mime_type": "image/jpeg"}
    if stated is not None:
        state["fuel_fields"] = stated
    return get_compiled_fuel_graph(deps).invoke(state)


def test_the_vehicle_and_amounts_the_user_states_beat_the_photo(backend: _FakeBackend) -> None:
    state = _photo_run(backend, {"vehicle_id": "v1", "liters_filled": 50, "price_per_liter": 280})

    record = state["created_record"]
    assert state["stage"] == "done"
    assert record["vehicle_id"] == "v1"  # not v2, the plate the photo shows
    assert (Decimal(record["liters_filled"]), Decimal(record["price_per_liter"]), Decimal(record["total_cost"])) == (50, 280, 14000)
    assert "Receipt shows plate LB-7967" in record["notes"]  # the disagreement is on the record


def test_a_plate_with_no_vehicle_id_is_accepted_as_the_stated_vehicle(backend: _FakeBackend) -> None:
    state = _photo_run(backend, {"vehicle_id": "ab 1234"})

    assert state["created_record"]["vehicle_id"] == "v1"
    assert Decimal(state["created_record"]["liters_filled"]) == Decimal("39.2")  # nothing else stated: the receipt's figures stand


def test_a_stated_vehicle_works_when_the_photo_shows_no_plate_at_all(backend: _FakeBackend) -> None:
    state = _photo_run(backend, {"vehicle_id": "v1"}, plate_number=None)

    assert state["stage"] == "done" and state["created_record"]["vehicle_id"] == "v1"
    assert "Receipt shows plate" not in (state["created_record"].get("notes") or "")


def test_a_stated_vehicle_that_does_not_exist_halts_instead_of_falling_back_to_the_photo(backend: _FakeBackend) -> None:
    state = _photo_run(backend, {"vehicle_id": "ZZ-9999"})

    assert state["stage"] == "halted" and "ZZ-9999" in state["halt_reason"]
    assert backend.create_fuel_calls == 0


@pytest.mark.parametrize(
    ("stated", "expected"),
    [
        ({}, (Decimal("39.2"), Decimal("391.9643"), Decimal("15365"))),  # the plain receipt: price derived
        ({"total_cost": 14000}, (Decimal("39.2"), Decimal("357.1429"), Decimal("14000"))),  # litres from the receipt
        ({"liters_filled": 50}, (Decimal("50"), Decimal("307.3"), Decimal("15365"))),  # total from the receipt
        ({"price_per_liter": 300}, (Decimal("39.2"), Decimal("300"), Decimal("11760.00"))),  # total = litres x price
        ({"liters_filled": 50, "total_cost": 14000}, (Decimal("50"), Decimal("280"), Decimal("14000"))),
        ({"total_cost": 14000, "price_per_liter": 280}, (Decimal("50.00"), Decimal("280"), Decimal("14000"))),  # litres = total / price
    ],
    ids=["receipt-only", "total-stated", "liters-stated", "price-stated", "liters+total", "total+price"],
)
def test_stated_figures_override_the_receipt_and_the_three_always_agree(backend: _FakeBackend, stated, expected) -> None:
    record = _photo_run(backend, {"vehicle_id": "v1", **stated})["created_record"]

    assert (Decimal(record["liters_filled"]), Decimal(record["price_per_liter"]), Decimal(record["total_cost"])) == expected


def test_a_stated_date_and_odometer_fill_what_the_photo_could_not_read(backend: _FakeBackend) -> None:
    unreadable = _photo_run(backend, {"vehicle_id": "v1"}, odometer=None)
    # Not on the photo and not stated: the vehicle's last recorded reading (1000) is the baseline, and the log says so.
    assert unreadable["stage"] == "done" and unreadable["created_record"]["odometer_reading"] == 1000
    assert "last recorded reading used" in unreadable["created_record"]["notes"]

    state = _photo_run(backend, {"vehicle_id": "v1", "odometer_reading": 1500, "date": "2026-09-30"}, odometer=None)
    assert state["stage"] == "done"
    assert (state["created_record"]["odometer_reading"], state["created_record"]["date"]) == (1500, "2026-09-30")


def test_without_enough_to_work_out_litres_and_cost_it_halts_with_a_reason(backend: _FakeBackend) -> None:
    state = _photo_run(backend, {"vehicle_id": "v1"}, liters=None, total_cost=None)

    assert state["stage"] == "halted" and "liters" in state["halt_reason"].lower()

