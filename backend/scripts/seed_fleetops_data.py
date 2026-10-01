"""Bulk, realistic mock data for the `fleetops` organization: a stress test for the Strategic Insights agent, the list
endpoints and pagination (hundreds of vehicles, thousands of drivers' worth of history, tens of thousands of logs).

    python scripts/seed_fleetops_data.py               # add the data (refuses if it is already there)
    python scripts/seed_fleetops_data.py --reset       # delete what this script created, then add it again
    python scripts/seed_fleetops_data.py --dry-run     # generate and check in memory, touch nothing
    python scripts/seed_fleetops_data.py --scale 0.1   # a tenth of the volume

Purely additive: it never touches existing rows. Everything it creates is recognisable (vehicle VINs start with SEEDV,
driver licenses with SD-), which is what --reset deletes. Runs only against a local database.

How the requested fields map onto this schema (the app has no column for some of them, and a migration for mock data
is not worth it):
  * vehicle `health_score`: no column. The Insights agent derives fleet health from the logs, which is what this feeds.
  * vehicle status "decommissioned" is the enum value `retired`. A retired vehicle's records all stop on its retirement
    date and its odometer is frozen there.
  * driver `hire_date`: no column; it is stored as the row's `created_at`, and nobody is assigned before it.
    Driver status "leave" is the enum value `inactive`.
  * fuel `product` ("Diesel", "Hi-Super"): kept in `notes` as "Product: Diesel; Station: PARCO", the format the fuel
    agent already writes. Diesel vehicles take Diesel, petrol ones Hi-Super.
  * maintenance `record_type` (routine / emergency): the description starts with "Routine service:" or "Emergency
    repair:", and an emergency is service_scale=major.
  * incident `status` open / resolved are `resolution_status` values.

Chronological consistency: a vehicle's odometer is built from its fuel fills (each fill advances it by liters x the
model's km/l), so odometers only go up; maintenance, assignments and everything else read the same odometer curve at
their own date. An assignment ends before the next one on the same vehicle begins, and a driver holds one vehicle at a
time, from their hire date on. Inserts are chunked executemany, so memory stays flat at any volume.
"""

from __future__ import annotations

import argparse
import bisect
import random
import string
import sys
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from faker import Faker  # noqa: E402
from sqlalchemy import delete, func, insert, select, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.models.accountability import DriverReport, IncidentLog, TripLog  # noqa: E402
from app.models.assignment import VehicleAssignment  # noqa: E402
from app.models.driver import Driver  # noqa: E402
from app.models.enums import (  # noqa: E402
    DriverStatus,
    IncidentResolutionStatus,
    IncidentSeverity,
    IncidentType,
    ServiceScale,
    ServiceType,
    VehicleCondition,
    VehicleFuelType,
    VehicleOwnershipType,
    VehicleStatus,
)
from app.models.fuel import FuelLog, FuelReceipt  # noqa: E402
from app.models.maintenance import MaintenanceLog, MaintenanceLogService, MechanicReport  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.vehicle import Vehicle  # noqa: E402

ORG_SLUG = "fleetops"
VIN_PREFIX = "SEEDV"
LICENSE_PREFIX = "SD-"
CHUNK = 5000
ANOMALY_THRESHOLD = Decimal("0.20")  # same rule as fuel_service: > 20% off the trailing 3-month average cost/km
MIN_ROLLING_HISTORY = 3

# make, model, fuel, km per liter, weight
CATALOG: list[tuple[str, str, str, float, int]] = [
    ("Toyota", "Hilux", "diesel", 9.0, 20), ("Toyota", "Hiace", "petrol", 8.0, 8), ("Toyota", "Corolla", "petrol", 12.5, 8),
    ("Ford", "Transit", "diesel", 9.5, 14), ("Ford", "Ranger", "diesel", 9.0, 8), ("Isuzu", "D-Max", "diesel", 10.0, 16),
    ("Isuzu", "NPR", "diesel", 7.0, 8), ("Suzuki", "Bolan", "petrol", 11.0, 6), ("Mercedes", "Sprinter", "diesel", 9.0, 7),
    ("Honda", "BR-V", "petrol", 11.5, 5),
]
STATIONS = ["PARCO", "Shell", "PSO", "Total", "Attock", "Hascol", "Caltex", "Byco"]
PAYMENT = [("fuel card", 60), ("cash", 25), ("bank transfer", 15)]
CITIES = ["Karachi", "Lahore", "Islamabad", "Rawalpindi", "Faisalabad", "Multan", "Peshawar", "Hyderabad", "Sukkur", "Gujranwala"]
ROADS = [
    "M-2 Motorway near Kallar Kahar", "GT Road, Gujranwala", "Shahrah-e-Faisal", "Ferozepur Road", "Kashmir Highway", "N-5 near Sukkur",
    "Super Highway, Karachi", "Canal Road, Faisalabad", "Murree Road", "Multan Bypass", "Hub River Road", "Ring Road, Peshawar",
]

# service type -> descriptions, (cost low, high) in PKR
SERVICES: dict[str, tuple[list[str], tuple[int, int]]] = {
    "oil_change": (["Oil change", "Engine oil and filter change"], (5_000, 18_000)),
    "brake_service": (["Brake pad replacement", "Brake replacement", "Brake fluid flush and rotor skim"], (9_000, 45_000)),
    "tire_rotation": (["Tire rotation and balancing", "Tire replacement"], (6_000, 60_000)),
    "engine_repair": (["Engine overhaul", "Engine misfire repair", "Radiator and cooling system repair"], (35_000, 150_000)),
    "transmission": (["Transmission overhaul", "Gearbox and clutch repair"], (45_000, 150_000)),
    "electrical": (["Alternator replacement", "Wiring and starter repair", "Battery replacement"], (8_000, 55_000)),
    "body_work": (["Panel beating and repaint", "Bumper and light replacement"], (12_000, 90_000)),
    "general_inspection": (["General inspection", "Pre-trip safety inspection"], (5_000, 12_000)),
    "other": (["Suspension repair", "Air-conditioning service"], (7_000, 60_000)),
}
ROUTINE_TYPES = [("oil_change", 40), ("general_inspection", 20), ("tire_rotation", 15), ("brake_service", 15), ("electrical", 5), ("other", 5)]
EMERGENCY_TYPES = [("engine_repair", 25), ("transmission", 20), ("brake_service", 20), ("electrical", 15), ("body_work", 15), ("other", 5)]

DAMAGE = {
    "minor": ["Scraped the rear bumper while reversing in the depot yard.", "Side mirror knocked off by a passing rickshaw on {road}.", "Small dent on the rear door from a loading-bay collision."],
    "moderate": ["Rear-ended by a motorcycle at a signal on {road}; bumper and tail light replaced.", "Collided with a roadside barrier on {road}, front-left panel and headlight damaged.", "Windscreen shattered by debris on {road}; driver unhurt."],
    "severe": ["Side-on collision with a truck at the {road} junction; front axle bent, vehicle towed.", "Rolled onto its side avoiding a cyclist on {road}; roof and doors crushed, driver treated for bruising."],
    "critical": ["Head-on collision with an oncoming bus on {road}; vehicle written off, driver hospitalised.", "Vehicle caught fire after a fuel line failure on {road}; total loss, driver escaped."],
}
VIOLATION = {
    "minor": ["Parked in a no-parking zone on {road}; fine issued.", "Seat-belt violation recorded at the {road} checkpoint."],
    "moderate": ["Overspeeding recorded on {road}; challan issued.", "Red light violation at the {road} intersection."],
    "severe": ["Overloaded vehicle stopped on {road}; load offloaded and fine paid.", "Driving with an expired route permit on {road}; vehicle impounded for a day."],
    "critical": ["Driver stopped on {road} under the influence; vehicle impounded and driver suspended."],
}
NEAR_MISS = {
    "minor": ["Brakes applied hard to avoid a pedestrian on {road}; no contact.", "Tyre blowout on {road}, vehicle stopped safely on the shoulder."],
    "moderate": ["Near collision with an overtaking bus on {road}; evasive manoeuvre.", "Brake fade on the descent at {road}; driver used the handbrake to stop."],
    "severe": ["Lost steering assist at speed on {road}; recovered without contact."],
    "critical": ["Wheel came loose at highway speed on {road}; vehicle stopped, no injuries."],
}
RESOLUTION = ["Repaired and returned to service.", "Insurance claim settled.", "Driver counselled; no further action.", "Fine paid by the company.", "Reviewed by the fleet manager and closed."]
SEVERITY_COST = {"minor": (2_000, 25_000), "moderate": (20_000, 120_000), "severe": (100_000, 600_000), "critical": (400_000, 2_000_000)}


@dataclass(frozen=True)
class Targets:
    vehicles: int = 520
    drivers: int = 820
    assignments: int = 10_400
    fuel_logs: int = 52_000
    maintenance_logs: int = 15_500
    incidents: int = 2_100
    years: int = 3

    def scaled(self, factor: float) -> Targets:
        return replace(
            self, vehicles=max(5, round(self.vehicles * factor)), drivers=max(8, round(self.drivers * factor)),
            assignments=max(20, round(self.assignments * factor)), fuel_logs=max(50, round(self.fuel_logs * factor)),
            maintenance_logs=max(20, round(self.maintenance_logs * factor)), incidents=max(10, round(self.incidents * factor)),
        )


def _pick(rng: random.Random, weighted: list[tuple[Any, int]]) -> Any:
    return rng.choices([v for v, _ in weighted], weights=[w for _, w in weighted])[0]


def _stamp(d: date, hour: int = 12) -> datetime:
    return datetime.combine(d, time(hour, 0), tzinfo=timezone.utc)


def _allocate(total: int, weights: list[int]) -> list[int]:
    """Split `total` across items in proportion to `weights`, exactly (largest remainder)."""
    scale = sum(weights) or 1
    raw = [total * w / scale for w in weights]
    counts = [int(x) for x in raw]
    for i in sorted(range(len(raw)), key=lambda i: raw[i] - counts[i], reverse=True)[: total - sum(counts)]:
        counts[i] += 1
    return counts


class VehicleSim:
    """One vehicle's timeline: its window, and an odometer curve (piecewise linear through its fuel fills)."""

    def __init__(self, row: dict[str, Any], t_start: date, t_end: date, kml: float):
        self.row, self.t_start, self.t_end, self.kml = row, t_start, t_end, kml
        self.knot_dates: list[date] = []
        self.knot_odos: list[int] = []
        self.intervals: list[tuple[date, date | None, uuid.UUID]] = []  # assignments: (start, end or None, driver)

    @property
    def days(self) -> int:
        return (self.t_end - self.t_start).days

    def odo(self, d: date) -> int:
        d = min(max(d, self.t_start), self.t_end)
        i = bisect.bisect_right(self.knot_dates, d)
        if i == 0:
            return self.knot_odos[0]
        if i == len(self.knot_dates):
            return self.knot_odos[-1]
        d0, d1, o0, o1 = self.knot_dates[i - 1], self.knot_dates[i], self.knot_odos[i - 1], self.knot_odos[i]
        return o0 + (o1 - o0) * (d - d0).days // max(1, (d1 - d0).days)

    def driver_at(self, d: date) -> uuid.UUID | None:
        i = bisect.bisect_right([s for s, _, _ in self.intervals], d) - 1
        if i < 0:
            return None
        start, end, driver = self.intervals[i]
        return driver if end is None or d <= end else None


def build_dataset(targets: Targets, *, org_id: uuid.UUID, admin_id: uuid.UUID | None, rng: random.Random, fake: Faker,
                  today: date, existing_plates: set[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Everything as lists of column dicts, ready for executemany. Pure: no database."""
    taken = set(existing_plates or ())
    window_start = today - timedelta(days=365 * targets.years)

    def audit(created: datetime) -> dict[str, Any]:
        return {"organization_id": org_id, "created_by": admin_id, "updated_by": admin_id, "created_at": created, "updated_at": created, "is_deleted": False}

    # ---- drivers ------------------------------------------------------------------------------------------
    drivers: list[dict[str, Any]] = []
    for n in range(targets.drivers):
        hired = today - timedelta(days=rng.randint(0, 365 * 10)) if rng.random() < 0.8 else window_start + timedelta(days=rng.randint(0, (today - window_start).days - 30))
        hired = min(hired, today - timedelta(days=30))
        issue = hired - timedelta(days=rng.randint(30, 365 * 6))
        expired = rng.random() < 0.05
        status = _pick(rng, [(DriverStatus.active, 85), (DriverStatus.suspended, 5), (DriverStatus.inactive, 10)])
        drivers.append({
            "id": uuid.uuid4(), "user_id": None, "full_name": fake.name(),
            "license_number": f"{LICENSE_PREFIX}{rng.choice(CITIES)[:3].upper()}-{issue.year}-{n:06d}",
            "license_expiry": today - timedelta(days=rng.randint(10, 400)) if expired else today + timedelta(days=rng.randint(60, 365 * 5)),
            "phone": f"+92-3{rng.randint(0, 4)}{rng.randint(0, 9)}-{rng.randint(1000000, 9999999)}",
            "license_type": rng.choice(["LTV", "HTV", "PSV"]), "license_issue_date": issue,
            "license_current_status": "expired" if expired else "valid", "status": status, **audit(_stamp(hired, 9)),
            "_hired": hired,
        })

    # ---- vehicles -----------------------------------------------------------------------------------------
    sims: list[VehicleSim] = []
    for _ in range(targets.vehicles):
        make, model, fuel, kml, _w = _pick(rng, [((m, mo, f, k, w), w) for m, mo, f, k, w in CATALOG])
        while True:
            plate = "".join(rng.choices(string.ascii_uppercase, k=3)) + "-" + f"{rng.randint(0, 999):03d}"
            if plate not in taken:
                taken.add(plate)
                break
        year = rng.randint(2018, today.year)
        status = _pick(rng, [(VehicleStatus.active, 82), (VehicleStatus.maintenance, 10), (VehicleStatus.retired, 8)])
        t_start = max(window_start, date(year, 1, 1) + timedelta(days=rng.randint(0, 120)))
        t_start = min(t_start, today - timedelta(days=200))
        t_end = today - timedelta(days=rng.randint(60, 540)) if status == VehicleStatus.retired else today
        t_end = max(t_end, t_start + timedelta(days=150))
        interval_km = rng.choice([5_000, 10_000])
        row = {
            "id": uuid.uuid4(), "plate_number": plate, "make": make, "model": model, "year": year,
            "vin": VIN_PREFIX + "".join(rng.choices(string.ascii_uppercase + string.digits, k=12)),
            "current_odometer": 0, "fuel_type": VehicleFuelType(fuel), "status": status,
            "service_interval_km": interval_km, "service_interval_months": 6 if interval_km == 5_000 else 12,
            "engine_number": f"ENG-{rng.randint(100000, 999999)}", "chassis_number": f"CHS-{rng.randint(10000000, 99999999)}",
            "ownership_type": _pick(rng, [(VehicleOwnershipType.owner, 60), (VehicleOwnershipType.leasing, 25), (VehicleOwnershipType.rent, 15)]),
            "added_by": admin_id, **audit(_stamp(t_start, 8)),
        }
        sims.append(VehicleSim(row, t_start, t_end, kml))

    # ---- fuel logs (these define each odometer curve) ------------------------------------------------------
    price = {"Diesel": 255.0, "Hi-Super": 268.0}  # PKR per liter, a random walk by month: the "volatility"
    price_by_month: dict[tuple[int, int], dict[str, float]] = {}
    cursor = date(window_start.year, window_start.month, 1)
    while cursor <= today:
        for product in price:
            price[product] = min(360.0, max(220.0, price[product] * rng.uniform(0.97, 1.045)))
        price_by_month[(cursor.year, cursor.month)] = dict(price)
        cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)

    fuel_rows: list[dict[str, Any]] = []
    counts = _allocate(targets.fuel_logs, [s.days for s in sims])
    for sim, n in zip(sims, counts):
        n = min(n, sim.days)
        offsets = sorted(rng.sample(range(1, sim.days + 1), n))
        dates = [sim.t_start + timedelta(days=o) for o in offsets]
        liters = [round(rng.uniform(30.0, 80.0), 2) for _ in dates]
        deltas = [max(1, round(l * sim.kml * rng.uniform(0.92, 1.08) * (rng.uniform(0.45, 0.65) if rng.random() < 0.025 else 1.0))) for l in liters]
        implied = sum(deltas)
        rate = implied / max(1, offsets[-1]) if offsets else 20.0
        tail = int(rate * (sim.t_end - dates[-1]).days) if dates else int(rate * sim.days)
        age = max(0, today.year - sim.row["year"])
        mean = 10_000 + age * 22_000
        target = int(min(245_000, max(10_000, rng.gauss(mean, 0.35 * mean))))
        base = int(min(max(target - implied - tail, 0), 249_000 - implied - tail))
        base = max(base, 0)

        sim.knot_dates, sim.knot_odos = [sim.t_start], [base]
        odo = base
        window: deque[tuple[date, Decimal]] = deque()  # (date, cost_per_km) of the trailing 3 months
        station_bias = rng.choice(STATIONS)
        card = f"**** {rng.randint(1000, 9999)}"
        product = "Diesel" if sim.row["fuel_type"] == VehicleFuelType.diesel else "Hi-Super"
        for d, lit, delta in zip(dates, liters, deltas):
            odo += delta
            sim.knot_dates.append(d)
            sim.knot_odos.append(odo)
            p = round(price_by_month[(d.year, d.month)][product] * rng.uniform(0.99, 1.012), 2)
            liters_d, price_d = Decimal(str(lit)), Decimal(str(p))
            total = (liters_d * price_d).quantize(Decimal("0.01"))
            cost_per_km, anomalous = None, False
            if len(sim.knot_dates) > 2:
                cost_per_km = (total / Decimal(delta)).quantize(Decimal("0.0001"))
                cutoff = date(d.year - (d.month <= 3), (d.month - 4) % 12 + 1, min(d.day, 28))
                while window and window[0][0] < cutoff:
                    window.popleft()
                if len(window) >= MIN_ROLLING_HISTORY:
                    avg = sum(c for _, c in window) / len(window)
                    anomalous = avg != 0 and abs(cost_per_km - avg) / avg > ANOMALY_THRESHOLD
                window.append((d, cost_per_km))
            station = station_bias if rng.random() < 0.6 else rng.choice(STATIONS)
            payment = _pick(rng, PAYMENT)
            fuel_rows.append({
                "id": uuid.uuid4(), "vehicle_id": sim.row["id"], "driver_id": None, "date": d, "odometer_reading": odo,
                "liters_filled": liters_d, "price_per_liter": price_d, "total_cost": total, "cost_per_km": cost_per_km,
                "is_anomalous": anomalous, "notes": f"Product: {product}; Station: {station}", "po_number": f"PO-{rng.randint(1000, 9999)}" if rng.random() < 0.3 else None,
                "payment_method": payment, "card_used": card if payment == "fuel card" else None, "fuel_station_name": station,
                "slip_id": f"SLP-{rng.randint(100000, 999999)}", **audit(_stamp(d, 15)), "_sim": sim,
            })
        end_odo = odo + tail
        if not sim.knot_dates or sim.knot_dates[-1] < sim.t_end:
            sim.knot_dates.append(sim.t_end)
            sim.knot_odos.append(end_odo)
        sim.row["current_odometer"] = sim.knot_odos[-1]

    # ---- assignments ---------------------------------------------------------------------------------------
    def chains(mean_len: float) -> list[tuple[VehicleSim, date, date | None]]:
        out: list[tuple[VehicleSim, date, date | None]] = []
        for sim in sims:
            cur = sim.t_start + timedelta(days=rng.randint(0, 20))
            while True:
                end = cur + timedelta(days=max(1, round(rng.uniform(0.2, 1.8) * mean_len)))
                if end >= sim.t_end:
                    if sim.row["status"] == VehicleStatus.active and rng.random() < 0.6 and cur < sim.t_end - timedelta(days=2):
                        out.append((sim, cur, None))  # still out with the driver
                    break
                out.append((sim, cur, end))
                cur = end + timedelta(days=rng.randint(1, 9))
        return out

    mean_len = 38.0
    planned = chains(mean_len)
    for _ in range(10):
        if len(planned) >= targets.assignments:
            break
        mean_len *= 0.8
        planned = chains(mean_len)
    planned.sort(key=lambda x: x[1])

    free_at: dict[uuid.UUID, date] = {d["id"]: date.min for d in drivers}
    hired = {d["id"]: d["_hired"] for d in drivers}
    active_ids = [d["id"] for d in drivers if d["status"] == DriverStatus.active]
    all_ids = [d["id"] for d in drivers]
    assignment_rows: list[dict[str, Any]] = []
    for sim, start, end in planned:
        pool = active_ids if end is None else all_ids
        driver = next((c for c in (rng.choice(pool) for _ in range(40)) if free_at[c] < start and hired[c] <= start), None)
        if driver is None:
            driver = next((c for c in pool if free_at[c] < start and hired[c] <= start), None)
        if driver is None:
            continue
        free_at[driver] = date.max if end is None else end
        sim.intervals.append((start, end, driver))
        take = _pick(rng, [(VehicleCondition.good, 70), (VehicleCondition.fair, 22), (VehicleCondition.poor, 8)])
        leave = None if end is None else (take if rng.random() < 0.7 else _pick(rng, [(VehicleCondition.fair, 50), (VehicleCondition.poor, 50)]) if take == VehicleCondition.good else VehicleCondition.poor)
        assignment_rows.append({
            "id": uuid.uuid4(), "vehicle_id": sim.row["id"], "driver_id": driver, "assigned_at": datetime.combine(start, time(rng.randint(6, 9), rng.choice([0, 15, 30, 45])), tzinfo=timezone.utc),
            "released_at": None if end is None else datetime.combine(end, time(rng.randint(16, 19), rng.choice([0, 15, 30, 45])), tzinfo=timezone.utc),
            "start_odometer": sim.odo(start), "end_odometer": None if end is None else sim.odo(end), "take_condition": take, "leave_condition": leave,
            "take_notes": rng.choice(["Fuel tank full.", "Minor scratches on the left side.", "Tyres checked.", None, None]) , "leave_notes": None if end is None else rng.choice(["Returned clean.", "Needs a wash.", "Check engine light on.", None, None]),
            **audit(_stamp(start, 9)),
        })
    for sim in sims:
        sim.intervals.sort(key=lambda t: t[0])
    for row in fuel_rows:  # who had the vehicle when it was filled
        sim = row.pop("_sim")
        row["driver_id"] = sim.driver_at(row["date"])

    # ---- maintenance -----------------------------------------------------------------------------------------
    maintenance_rows: list[dict[str, Any]] = []
    service_rows: list[dict[str, Any]] = []
    for sim, n in zip(sims, _allocate(targets.maintenance_logs, [s.days for s in sims])):
        n = min(n, sim.days)
        for off in sorted(rng.sample(range(1, sim.days + 1), n)):
            d = sim.t_start + timedelta(days=off)
            emergency = rng.random() < 0.18
            primary = _pick(rng, EMERGENCY_TYPES if emergency else ROUTINE_TYPES)
            types = [primary]
            if not emergency and rng.random() < 0.3:
                types += rng.sample([t for t in ("oil_change", "general_inspection", "tire_rotation", "brake_service") if t != primary], rng.randint(1, 2))
            desc = " and ".join(rng.choice(SERVICES[t][0]) for t in types)
            lo, hi = SERVICES[primary][1]
            cost = int(min(150_000, max(5_000, rng.uniform(lo, hi) * (1 + 0.25 * (len(types) - 1)))))
            log_id = uuid.uuid4()
            odo = sim.odo(d)
            major = emergency or primary in ("engine_repair", "transmission")
            maintenance_rows.append({
                "id": log_id, "vehicle_id": sim.row["id"], "date": d, "odometer_at_service": odo, "service_type": ServiceType(primary),
                "description": f"{'Emergency repair' if emergency else 'Routine service'}: {desc}", "cost": Decimal(cost),
                "mechanic_name": fake.name(), "service_scale": ServiceScale.major if major else ServiceScale.minor,
                "driver_id": sim.driver_at(d) if rng.random() < 0.6 else None,
                "next_due_km": odo + sim.row["service_interval_km"], "next_due_date": d + timedelta(days=30 * sim.row["service_interval_months"]),
                **audit(_stamp(d, 17)),
            })
            service_rows += [{"id": uuid.uuid4(), "maintenance_log_id": log_id, "service_type": ServiceType(t), "position": i} for i, t in enumerate(types)]

    # ---- incidents ---------------------------------------------------------------------------------------------
    incident_rows: list[dict[str, Any]] = []
    for sim, n in zip(sims, _allocate(targets.incidents, [s.days for s in sims])):
        n = min(n, sim.days)
        for off in sorted(rng.sample(range(1, sim.days + 1), n)):
            d = sim.t_start + timedelta(days=off)
            severity = _pick(rng, [("minor", 50), ("moderate", 28), ("severe", 15), ("critical", 7)])
            kind = _pick(rng, [(IncidentType.damage, 60), (IncidentType.violation, 25), (IncidentType.near_miss, 15)])
            table = {IncidentType.damage: DAMAGE, IncidentType.violation: VIOLATION, IncidentType.near_miss: NEAR_MISS}[kind]
            road = rng.choice(ROADS)
            age = (today - d).days
            resolved = rng.random() < (0.95 if age > 90 else 0.6 if age > 30 else 0.2) * (0.7 if severity == "critical" else 1.0)
            lo, hi = SEVERITY_COST[severity]
            driver = sim.driver_at(d) or rng.choice(drivers)["id"]
            incident_rows.append({
                "id": uuid.uuid4(), "driver_id": driver, "vehicle_id": sim.row["id"], "incident_type": kind,
                "incident_time": datetime.combine(d, time(rng.randint(5, 22), rng.randint(0, 59)), tzinfo=timezone.utc), "date": d,
                "severity": IncidentSeverity(severity), "description": rng.choice(table[severity]).format(road=road),
                "location_description": road, "location_area": rng.choice(CITIES), "remarks": None, "attachment_url": None,
                "estimated_cost": Decimal(int(rng.uniform(lo, hi) // 100 * 100)) if kind != IncidentType.near_miss or rng.random() < 0.3 else None,
                "resolution_status": IncidentResolutionStatus.resolved if resolved else IncidentResolutionStatus.open,
                "resolution_notes": rng.choice(RESOLUTION) if resolved else None, **audit(_stamp(d, 20)),
            })

    vehicles = [dict(sim.row) for sim in sims]
    for row in vehicles:
        row["organization_id"] = org_id
    for d in drivers:
        d.pop("_hired")
    for rows in (assignment_rows, fuel_rows, maintenance_rows, incident_rows):
        for row in rows:
            row["organization_id"] = org_id
    return {"vehicles": vehicles, "drivers": drivers, "vehicle_assignments": assignment_rows, "fuel_logs": fuel_rows,
            "maintenance_logs": maintenance_rows, "maintenance_log_services": service_rows, "incident_logs": incident_rows}


# --------------------------------------------------------------------------------------------------------------
# database side
# --------------------------------------------------------------------------------------------------------------

MODELS = {
    "drivers": Driver, "vehicles": Vehicle, "vehicle_assignments": VehicleAssignment, "fuel_logs": FuelLog,
    "maintenance_logs": MaintenanceLog, "maintenance_log_services": MaintenanceLogService, "incident_logs": IncidentLog,
}
INSERT_ORDER = ["drivers", "vehicles", "vehicle_assignments", "fuel_logs", "maintenance_logs", "maintenance_log_services", "incident_logs"]


def bulk_insert(session, model, rows: list[dict[str, Any]]) -> None:
    """Chunked executemany: memory holds one chunk of parameters at a time."""
    for i in range(0, len(rows), CHUNK):
        session.execute(insert(model), rows[i : i + CHUNK])


def assert_local_database() -> None:
    host = make_url(get_settings().database_url).host or ""
    if host not in ("localhost", "127.0.0.1", "::1", "db", "postgres"):
        raise SystemExit(f"Refusing to seed mock data into a non-local database host: {host!r}")


def reset(session, org_id: uuid.UUID) -> dict[str, int]:
    """Delete exactly what this script created (seed VINs / license prefix), child tables first."""
    vehicle_ids = select(Vehicle.id).where(Vehicle.organization_id == org_id, Vehicle.vin.like(f"{VIN_PREFIX}%"))
    driver_ids = select(Driver.id).where(Driver.organization_id == org_id, Driver.license_number.like(f"{LICENSE_PREFIX}%"))
    removed: dict[str, int] = {}
    log_ids = select(MaintenanceLog.id).where(MaintenanceLog.vehicle_id.in_(vehicle_ids))
    steps = [
        ("maintenance_log_services", delete(MaintenanceLogService).where(MaintenanceLogService.maintenance_log_id.in_(log_ids))),
        ("mechanic_reports", delete(MechanicReport).where(MechanicReport.maintenance_log_id.in_(log_ids))),
        ("maintenance_logs", delete(MaintenanceLog).where(MaintenanceLog.vehicle_id.in_(vehicle_ids))),
        ("fuel_receipts", delete(FuelReceipt).where(FuelReceipt.fuel_log_id.in_(select(FuelLog.id).where(FuelLog.vehicle_id.in_(vehicle_ids))))),
        ("fuel_logs", delete(FuelLog).where(FuelLog.vehicle_id.in_(vehicle_ids))),
        ("incident_logs", delete(IncidentLog).where(IncidentLog.vehicle_id.in_(vehicle_ids))),
        ("vehicle_assignments", delete(VehicleAssignment).where(VehicleAssignment.vehicle_id.in_(vehicle_ids))),
        ("trip_logs", delete(TripLog).where(TripLog.vehicle_id.in_(vehicle_ids))),
        ("driver_reports", delete(DriverReport).where(DriverReport.vehicle_id.in_(vehicle_ids))),
        ("vehicles", delete(Vehicle).where(Vehicle.organization_id == org_id, Vehicle.vin.like(f"{VIN_PREFIX}%"))),
        ("drivers", delete(Driver).where(Driver.id.in_(driver_ids))),
    ]
    for name, stmt in steps:
        removed[name] = session.execute(stmt).rowcount or 0
    return removed


def verify(session, org_id: uuid.UUID) -> bool:
    """Print what is in the database and check the chronological invariants. True when every check passes."""
    org = {"o": org_id}
    seed_v = f"vehicle_id IN (SELECT id FROM vehicles WHERE organization_id = :o AND vin LIKE '{VIN_PREFIX}%')"
    print("\n=== Row counts for the fleetops organization (seeded / total) ===")
    tables = [("vehicles", f"vin LIKE '{VIN_PREFIX}%'"), ("drivers", f"license_number LIKE '{LICENSE_PREFIX}%'"), ("vehicle_assignments", seed_v),
              ("fuel_logs", seed_v), ("maintenance_logs", seed_v), ("maintenance_log_services", f"maintenance_log_id IN (SELECT id FROM maintenance_logs WHERE {seed_v})"),
              ("incident_logs", seed_v)]
    for table, seeded in tables:
        scoped = "" if table == "maintenance_log_services" else "organization_id = :o AND "
        total = session.execute(text(f"SELECT count(*) FROM {table}" + ("" if table == "maintenance_log_services" else " WHERE organization_id = :o")), org).scalar()
        mine = session.execute(text(f"SELECT count(*) FROM {table} WHERE {scoped}{seeded}"), org).scalar()
        print(f"  {table:28s} {mine:>8,} / {total:>8,}")

    checks = {
        "fuel odometer strictly increasing per vehicle": f"SELECT count(*) FROM (SELECT odometer_reading - lag(odometer_reading) OVER (PARTITION BY vehicle_id ORDER BY date) AS d FROM fuel_logs WHERE {seed_v}) t WHERE d <= 0",
        "maintenance odometer never decreases": f"SELECT count(*) FROM (SELECT odometer_at_service - lag(odometer_at_service) OVER (PARTITION BY vehicle_id ORDER BY date) AS d FROM maintenance_logs WHERE {seed_v}) t WHERE d < 0",
        "current_odometer >= every logged reading": f"SELECT count(*) FROM vehicles v WHERE v.organization_id = :o AND v.vin LIKE '{VIN_PREFIX}%' AND v.current_odometer < GREATEST(COALESCE((SELECT max(odometer_reading) FROM fuel_logs WHERE vehicle_id = v.id), 0), COALESCE((SELECT max(odometer_at_service) FROM maintenance_logs WHERE vehicle_id = v.id), 0))",
        "no overlapping assignments on a vehicle": f"SELECT count(*) FROM vehicle_assignments a JOIN vehicle_assignments b ON a.vehicle_id = b.vehicle_id AND a.id < b.id AND a.assigned_at < COALESCE(b.released_at, 'infinity') AND b.assigned_at < COALESCE(a.released_at, 'infinity') WHERE a.{seed_v}",
        "no driver on two vehicles at once": f"SELECT count(*) FROM vehicle_assignments a JOIN vehicle_assignments b ON a.driver_id = b.driver_id AND a.id < b.id AND a.assigned_at < COALESCE(b.released_at, 'infinity') AND b.assigned_at < COALESCE(a.released_at, 'infinity') WHERE a.{seed_v}",
        "assignment end odometer >= start": f"SELECT count(*) FROM vehicle_assignments WHERE end_odometer < start_odometer AND {seed_v}",
    }
    ok = True
    print("\n=== Invariants (violations, expect 0) ===")
    for name, sql in checks.items():
        bad = session.execute(text(sql), org).scalar()
        ok &= bad == 0
        print(f"  {'OK  ' if bad == 0 else 'FAIL'} {name}: {bad}")
    status = session.execute(text(f"SELECT status, count(*) FROM vehicles WHERE organization_id = :o AND vin LIKE '{VIN_PREFIX}%' GROUP BY status ORDER BY status"), org).all()
    print("\n  seeded vehicles by status:", {s.value if hasattr(s, 'value') else s: c for s, c in status})
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--reset", action="store_true", help="delete what this script created before inserting")
    parser.add_argument("--dry-run", action="store_true", help="generate and report, insert nothing")
    parser.add_argument("--scale", type=float, default=1.0, help="volume factor (default 1.0 = the full set)")
    parser.add_argument("--seed", type=int, default=20260930, help="random seed (same seed, same data)")
    args = parser.parse_args(argv)
    targets = Targets().scaled(args.scale) if args.scale != 1.0 else Targets()

    assert_local_database()
    from app.core.database import SessionLocal

    session = SessionLocal()
    try:
        org = session.execute(select(Organization).where(Organization.slug == ORG_SLUG)).scalar_one_or_none()
        if org is None:
            raise SystemExit(f"Organization {ORG_SLUG!r} not found -- run seed_dummy_data.py first.")
        admin_id = session.execute(select(User.id).where(User.organization_id == org.id, User.email == "admin@fleetops.com")).scalar_one_or_none()
        existing = session.execute(select(func.count()).select_from(Vehicle).where(Vehicle.organization_id == org.id, Vehicle.vin.like(f"{VIN_PREFIX}%"))).scalar()
        if existing and not args.reset and not args.dry_run:
            raise SystemExit(f"{existing} seeded vehicles already exist. Use --reset to replace them.")

        if args.reset and not args.dry_run:
            print("Removed:", reset(session, org.id))
            session.commit()
        plates = set(session.execute(select(Vehicle.plate_number).where(Vehicle.organization_id == org.id)).scalars())
        rng, fake = random.Random(args.seed), Faker("en_US")
        Faker.seed(args.seed)
        print(f"Generating for {ORG_SLUG!r}: {targets}")
        data = build_dataset(targets, org_id=org.id, admin_id=admin_id, rng=rng, fake=fake, today=date.today(), existing_plates=plates)
        if args.dry_run:
            print({name: len(rows) for name, rows in data.items()})
            return 0
        for name in INSERT_ORDER:
            bulk_insert(session, MODELS[name], data[name])
            print(f"  inserted {len(data[name]):>7,} {name}")
        session.commit()
        return 0 if verify(session, org.id) else 1
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
