"""The fleetops mock-data generator: the invariants the Insights agent and the list endpoints rely on, checked on a
small in-memory dataset (no database)."""

import importlib.util
import random
import re
import sys
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from faker import Faker

from app.models.enums import DriverStatus, IncidentResolutionStatus, VehicleStatus

_spec = importlib.util.spec_from_file_location("seed_fleetops_data", Path(__file__).resolve().parent.parent / "scripts" / "seed_fleetops_data.py")
seed = importlib.util.module_from_spec(_spec)
sys.modules["seed_fleetops_data"] = seed  # dataclasses resolve their module through sys.modules
_spec.loader.exec_module(seed)

TODAY = date(2026, 10, 1)
TARGETS = seed.Targets(vehicles=60, drivers=90, assignments=1_200, fuel_logs=5_000, maintenance_logs=1_500, incidents=240)


@pytest.fixture(scope="module")
def data():
    Faker.seed(7)
    return seed.build_dataset(TARGETS, org_id=uuid.uuid4(), admin_id=uuid.uuid4(), rng=random.Random(7), fake=Faker("en_US"), today=TODAY, existing_plates={"AAA-000"})


def by_vehicle(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["vehicle_id"]].append(row)
    return grouped


def test_volumes_hit_the_targets(data) -> None:
    assert len(data["vehicles"]) == 60 and len(data["drivers"]) == 90
    assert len(data["fuel_logs"]) == 5_000 and len(data["maintenance_logs"]) == 1_500 and len(data["incident_logs"]) == 240
    assert len(data["vehicle_assignments"]) >= 1_200  # the chains are re-tuned until the target is met


def test_the_full_size_defaults_meet_the_requested_minimums() -> None:
    full = seed.Targets()
    assert (full.vehicles, full.drivers, full.assignments, full.fuel_logs, full.maintenance_logs, full.incidents) >= (500, 800, 10_000, 50_000, 15_000, 2_000)


def test_vehicles_are_unique_plausible_and_seed_marked(data) -> None:
    vehicles = data["vehicles"]
    plates = [v["plate_number"] for v in vehicles]
    assert len(set(plates)) == len(plates) and "AAA-000" not in plates  # never collides with an existing plate
    assert all(re.fullmatch(r"[A-Z]{3}-\d{3}", p) for p in plates)
    assert len({v["vin"] for v in vehicles}) == len(vehicles) and all(len(v["vin"]) == 17 and v["vin"].startswith("SEEDV") for v in vehicles)
    assert all(2018 <= v["year"] <= 2026 and 10_000 <= v["current_odometer"] <= 250_000 for v in vehicles)
    assert {v["make"] for v in vehicles} >= {"Toyota", "Ford", "Isuzu"}
    assert {v["status"] for v in vehicles} == {VehicleStatus.active, VehicleStatus.maintenance, VehicleStatus.retired}


def test_drivers_are_seed_marked_and_have_every_status(data) -> None:
    assert all(d["license_number"].startswith("SD-") for d in data["drivers"])
    assert len({d["license_number"] for d in data["drivers"]}) == 90
    assert {d["status"] for d in data["drivers"]} == {DriverStatus.active, DriverStatus.suspended, DriverStatus.inactive}


def test_fuel_odometers_only_go_up_and_the_figures_add_up(data) -> None:
    for logs in by_vehicle(data["fuel_logs"]).values():
        logs.sort(key=lambda r: r["date"])
        readings = [r["odometer_reading"] for r in logs]
        assert all(b > a for a, b in zip(readings, readings[1:]))
        assert len({r["date"] for r in logs}) == len(logs)
    for row in data["fuel_logs"]:
        assert Decimal("30") <= row["liters_filled"] <= Decimal("80")
        assert row["total_cost"] == (row["liters_filled"] * row["price_per_liter"]).quantize(Decimal("0.01"))
        assert row["fuel_station_name"] in seed.STATIONS and row["notes"].startswith("Product: ")


def test_fuel_dates_span_three_years_and_never_pass_today(data) -> None:
    dates = [r["date"] for r in data["fuel_logs"]]
    assert max(dates) <= TODAY and (max(dates) - min(dates)).days > 365 * 2


def test_diesel_vehicles_take_diesel_and_petrol_ones_hi_super(data) -> None:
    fuel = {v["id"]: v["fuel_type"].value for v in data["vehicles"]}
    for row in data["fuel_logs"]:
        assert row["notes"].startswith("Product: Diesel" if fuel[row["vehicle_id"]] == "diesel" else "Product: Hi-Super")


def test_the_vehicles_current_odometer_is_at_least_every_reading(data) -> None:
    current = {v["id"]: v["current_odometer"] for v in data["vehicles"]}
    for row in data["fuel_logs"]:
        assert row["odometer_reading"] <= current[row["vehicle_id"]]
    for row in data["maintenance_logs"]:
        assert row["odometer_at_service"] <= current[row["vehicle_id"]]


def test_maintenance_is_chronological_costed_and_has_its_service_rows(data) -> None:
    for logs in by_vehicle(data["maintenance_logs"]).values():
        logs.sort(key=lambda r: r["date"])
        readings = [r["odometer_at_service"] for r in logs]
        assert all(b >= a for a, b in zip(readings, readings[1:]))
    assert all(5_000 <= row["cost"] <= 150_000 for row in data["maintenance_logs"])
    kinds = {row["description"].split(":")[0] for row in data["maintenance_logs"]}
    assert kinds == {"Routine service", "Emergency repair"}
    services = defaultdict(list)
    for s in data["maintenance_log_services"]:
        services[s["maintenance_log_id"]].append(s)
    for log in data["maintenance_logs"]:
        rows = services[log["id"]]
        assert rows and rows[0]["service_type"] == log["service_type"]
        assert len({r["service_type"] for r in rows}) == len(rows)  # unique (log, type), as the table requires


def test_assignments_never_overlap_on_a_vehicle_or_for_a_driver(data) -> None:
    for key in ("vehicle_id", "driver_id"):
        for rows in by_vehicle_key(data["vehicle_assignments"], key).values():
            rows.sort(key=lambda r: r["assigned_at"])
            for a, b in zip(rows, rows[1:]):
                assert a["released_at"] is not None and a["released_at"] <= b["assigned_at"], (key, a, b)


def by_vehicle_key(rows, key):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row[key]].append(row)
    return grouped


def test_open_assignments_are_only_on_active_vehicles_with_active_drivers(data) -> None:
    status = {v["id"]: v["status"] for v in data["vehicles"]}
    drivers = {d["id"]: d["status"] for d in data["drivers"]}
    open_rows = [r for r in data["vehicle_assignments"] if r["released_at"] is None]
    assert open_rows
    assert all(status[r["vehicle_id"]] == VehicleStatus.active and drivers[r["driver_id"]] == DriverStatus.active for r in open_rows)
    assert all(r["end_odometer"] is None and r["leave_condition"] is None for r in open_rows)
    assert all(r["end_odometer"] >= r["start_odometer"] for r in data["vehicle_assignments"] if r["released_at"])


def test_nobody_is_assigned_before_they_were_hired_and_retired_vehicles_stop_at_retirement(data) -> None:
    hired = {d["id"]: d["created_at"] for d in data["drivers"]}
    for r in data["vehicle_assignments"]:
        assert r["assigned_at"].date() >= hired[r["driver_id"]].date()
    retired = {v["id"] for v in data["vehicles"] if v["status"] == VehicleStatus.retired}
    for r in data["vehicle_assignments"]:
        if r["vehicle_id"] in retired:
            assert r["released_at"] is not None


def test_incidents_reference_real_rows_and_resolve_with_age(data) -> None:
    vehicles, drivers = {v["id"] for v in data["vehicles"]}, {d["id"] for d in data["drivers"]}
    assert all(i["vehicle_id"] in vehicles and i["driver_id"] in drivers for i in data["incident_logs"])
    assert {i["severity"].value for i in data["incident_logs"]} == {"minor", "moderate", "severe", "critical"}
    old = [i for i in data["incident_logs"] if (TODAY - i["date"]).days > 90]
    recent = [i for i in data["incident_logs"] if (TODAY - i["date"]).days <= 30]
    resolved = lambda rows: sum(i["resolution_status"] == IncidentResolutionStatus.resolved for i in rows) / max(1, len(rows))  # noqa: E731
    assert resolved(old) > 0.8 and resolved(recent) < 0.5
    assert all(i["description"] and "{road}" not in i["description"] for i in data["incident_logs"])


def test_the_same_seed_gives_the_same_data() -> None:
    def run():
        Faker.seed(3)
        return seed.build_dataset(seed.Targets().scaled(0.05), org_id=uuid.UUID(int=1), admin_id=None, rng=random.Random(3), fake=Faker("en_US"), today=TODAY)

    a, b = run(), run()
    assert [v["plate_number"] for v in a["vehicles"]] == [v["plate_number"] for v in b["vehicles"]]
    assert [f["odometer_reading"] for f in a["fuel_logs"]] == [f["odometer_reading"] for f in b["fuel_logs"]]


def test_a_non_local_database_is_refused(monkeypatch) -> None:
    class Settings:
        database_url = "postgresql+psycopg://u:p@prod-db.example.com:5432/fleet"

    monkeypatch.setattr(seed, "get_settings", lambda: Settings())
    with pytest.raises(SystemExit):
        seed.assert_local_database()
