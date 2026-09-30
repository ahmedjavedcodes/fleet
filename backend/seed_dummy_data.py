"""Seed the local database from FleetOps_Test_Data.xlsx.

    python seed_dummy_data.py [path/to/workbook.xlsx]

Run against an EMPTY database (alembic downgrade base && alembic upgrade head);
it refuses to run if an organization already exists.

Insert order (foreign-key safe): organization -> users -> drivers -> suppliers ->
vehicles -> assignments -> operations (fuel, trips, maintenance, incidents).

Foundation rows are inserted through the SQLAlchemy models. Assignments and the
operational rows go through the service layer (which uses the same models and
session) so the app's own invariants apply: odometer only moves forward, fuel
cost_per_km/anomaly, maintenance next-due, one active assignment per vehicle and
per driver. Each service call commits on its own, so a failure part-way leaves a
partial seed -- just re-wipe and re-run.

The workbook is read with the stdlib (no openpyxl dependency).
"""

from __future__ import annotations

import re
import sys
import uuid
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.driver import Driver
from app.models.enums import (
    IncidentSeverity,
    IncidentType,
    ServiceScale,
    ServiceType,
    SupplierCategory,
    UserRole,
    VehicleCondition,
    VehicleFuelType,
    VehicleOwnershipType,
)
from app.models.organization import Organization
from app.models.supplier import Supplier
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.accountability import IncidentLogCreate, TripLogCreate
from app.schemas.assignment import VehicleAssignRequest
from app.schemas.fuel import FuelLogCreate
from app.schemas.maintenance import MaintenanceLogCreate
from app.services import assignment_service, fuel_service, incident_service, maintenance_service, trip_service

DEFAULT_WORKBOOK = Path(__file__).resolve().parent.parent / "FleetOps_Test_Data.xlsx"
ORG_NAME = "FleetOps"
ORG_SLUG = "fleetops"
# The workbook holds naive local times; the fleet is in Pakistan (UTC+5, no DST).
PKT = timezone(timedelta(hours=5))
# Not in the workbook. Driver.license_expiry is required, so derive a plausible one.
LICENSE_VALID_YEARS = 10

ROLE_MAP = {"admin": UserRole.admin, "fleet manager": UserRole.fleet_manager, "driver": UserRole.driver}
CATEGORY_MAP = {
    "workshop": SupplierCategory.workshop,
    "tire_supplier": SupplierCategory.tire_supplier,
    "parts": SupplierCategory.parts_supplier,
    "parts_supplier": SupplierCategory.parts_supplier,
    "fuel_station": SupplierCategory.fuel_station,
    "other": SupplierCategory.other,
}
# The workbook's service names are broader than our ServiceType enum.
SERVICE_MAP = {
    "oil change": ServiceType.oil_change,
    "brake inspection": ServiceType.brake_service,
    "brake service": ServiceType.brake_service,
    "filter replacement": ServiceType.other,
    "tire rotation": ServiceType.tire_rotation,
    "engine repair": ServiceType.engine_repair,
    "transmission": ServiceType.transmission,
    "electrical": ServiceType.electrical,
    "body work": ServiceType.body_work,
    "general inspection": ServiceType.general_inspection,
    "other": ServiceType.other,
}
SEVERITY_MAP = {
    "minor": IncidentSeverity.minor,
    "medium": IncidentSeverity.moderate,
    "moderate": IncidentSeverity.moderate,
    "high": IncidentSeverity.severe,
    "severe": IncidentSeverity.severe,
    "critical": IncidentSeverity.critical,
}
INCIDENT_TYPE_MAP = {
    "minor collision": IncidentType.damage,
    "collision": IncidentType.damage,
    "damage": IncidentType.damage,
    "violation": IncidentType.violation,
    "near miss": IncidentType.near_miss,
    "near_miss": IncidentType.near_miss,
}


# --- Workbook reading (stdlib) ---------------------------------------------------------

_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):  # type: ignore[union-attr]
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_workbook(path: Path) -> dict[str, list[list[object]]]:
    z = zipfile.ZipFile(path)
    shared: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % _NS["m"])))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    sheets: dict[str, list[list[object]]] = {}
    for sheet in ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", _NS):  # type: ignore[union-attr]
        target = rels[sheet.get("{%s}id" % _NS["r"])].lstrip("/")
        target = target if target.startswith("xl/") else "xl/" + target
        rows: list[list[object]] = []
        for row in ET.fromstring(z.read(target)).iter("{%s}row" % _NS["m"]):
            cells: dict[int, object] = {}
            for c in row.findall("m:c", _NS):
                kind, v = c.get("t"), c.find("m:v", _NS)
                if kind == "inlineStr":
                    val: object = "".join(t.text or "" for t in c.iter("{%s}t" % _NS["m"]))
                elif v is None or v.text is None:
                    val = None
                elif kind == "s":
                    val = shared[int(v.text)]
                elif kind in ("str", "e"):
                    val = v.text
                elif kind == "b":
                    val = v.text == "1"
                else:
                    val = float(v.text) if ("." in v.text or "E" in v.text) else int(v.text)
                cells[_col_index(c.get("r"))] = val
            rows.append([cells.get(i) for i in range(max(cells) + 1)] if cells else [])
        sheets[sheet.get("name")] = rows
    return sheets


def table(sheets: dict[str, list[list[object]]], name: str) -> list[dict[str, object]]:
    """Header + data rows as dicts. Footnote rows (a single filled cell) are skipped."""
    rows = sheets[name]
    header = [str(h).strip() for h in rows[0]]
    out = []
    for row in rows[1:]:
        if sum(1 for cell in row if cell not in (None, "")) < 2:
            continue
        out.append({h: (row[i] if i < len(row) else None) for i, h in enumerate(header)})
    return out


def xl_date(serial: object) -> date:
    return date(1899, 12, 30) + timedelta(days=int(float(serial)))  # type: ignore[arg-type]


def xl_datetime(serial: object) -> datetime:
    """Excel serial (date + day fraction) -> minute-precision PKT datetime."""
    value = float(serial)  # type: ignore[arg-type]
    minutes = round((value - int(value)) * 1440)
    return datetime.combine(xl_date(value), time(0), tzinfo=PKT) + timedelta(minutes=minutes)


def text(value: object) -> str | None:
    return None if value in (None, "") else str(value).strip()


def mapped(mapping: dict, raw: object, what: str):
    key = str(raw).strip().lower()
    if key not in mapping:
        raise ValueError(f"Unmapped {what} value {raw!r}; known: {sorted(mapping)}")
    return mapping[key]


def add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # Feb 29
        return d.replace(year=d.year + years, day=28)


# --- Seeding ---------------------------------------------------------------------------


def seed(workbook: Path) -> None:
    sheets = read_workbook(workbook)
    with SessionLocal() as db:
        if db.execute(select(func.count(Organization.id))).scalar():
            raise SystemExit("Database already has an organization -- wipe it first (alembic downgrade base && upgrade head).")

        # 1. Organization + users -------------------------------------------------------
        org = Organization(id=uuid.uuid4(), name=ORG_NAME, slug=ORG_SLUG)
        db.add(org)
        db.flush()

        driver_rows = {str(r["License No"]).strip(): r for r in table(sheets, "Drivers")}
        users: dict[str, User] = {}  # email -> user
        user_by_license: dict[str, User] = {}
        for r in table(sheets, "Users"):
            role = mapped(ROLE_MAP, r["Role"], "user role")
            license_no = text(r.get("Linked Driver License No"))
            user = User(
                id=uuid.uuid4(),
                organization_id=org.id,
                email=str(r["Email / Login"]).strip().lower(),
                hashed_password=hash_password(str(r["Password (test only)"])),
                full_name=str(r["Name"]).strip(),
                phone=text(driver_rows[license_no]["Phone"]) if license_no else None,
                role=role,
            )
            db.add(user)
            users[user.email] = user
            if license_no:
                user_by_license[license_no] = user
        db.flush()
        admin = next(u for u in users.values() if u.role == UserRole.admin)

        # 2. Drivers (linked to their user by license number) ---------------------------
        drivers: dict[str, Driver] = {}  # full_name -> driver
        for license_no, r in driver_rows.items():
            issued = xl_date(r["License Issue Date"])
            driver = Driver(
                id=uuid.uuid4(),
                organization_id=org.id,
                created_by=admin.id,
                user_id=user_by_license[license_no].id if license_no in user_by_license else None,
                full_name=str(r["Name"]).strip(),
                phone=str(r["Phone"]).strip(),
                license_number=license_no,
                license_type=text(r["License Type"]),
                license_issue_date=issued,
                license_expiry=add_years(issued, LICENSE_VALID_YEARS),
                license_current_status=text(r["License Current Status"]),
            )
            db.add(driver)
            drivers[driver.full_name] = driver

        # 3. Suppliers ------------------------------------------------------------------
        suppliers: dict[str, Supplier] = {}
        for r in table(sheets, "Suppliers"):
            supplier = Supplier(
                id=uuid.uuid4(),
                organization_id=org.id,
                created_by=admin.id,
                name=str(r["Name"]).strip(),
                address=text(r["Address"]),
                phone=text(r["Phone"]),
                category=mapped(CATEGORY_MAP, r["Category"], "supplier category"),
            )
            db.add(supplier)
            suppliers[supplier.name] = supplier

        # 4. Vehicles -------------------------------------------------------------------
        vehicles: dict[str, Vehicle] = {}  # plate -> vehicle
        for r in table(sheets, "Vehicles"):
            chassis = str(r["VIN / Chassis No"]).strip()
            vehicle = Vehicle(
                id=uuid.uuid4(),
                organization_id=org.id,
                created_by=admin.id,
                added_by=admin.id,
                plate_number=str(r["Plate"]).strip(),
                make=str(r["Make"]).strip(),
                model=str(r["Model"]).strip(),
                year=int(r["Year"]),  # type: ignore[arg-type]
                vin=chassis,  # the workbook has one "VIN / Chassis No" column
                chassis_number=chassis,
                engine_number=text(r["Engine No"]),
                ownership_type=VehicleOwnershipType(str(r["Ownership Type"]).strip().lower()),
                fuel_type=VehicleFuelType(str(r["Fuel Type"]).strip().lower()),
                current_odometer=int(r["Odometer (km)"]),  # type: ignore[arg-type]
            )
            db.add(vehicle)
            vehicles[vehicle.plate_number] = vehicle
        db.commit()

        def vehicle_of(plate: object) -> Vehicle:
            return vehicles[str(plate).strip()]

        def driver_of(name: object) -> Driver:
            return drivers[str(name).strip()]

        # 5. Assignments ----------------------------------------------------------------
        for r in table(sheets, "Assignments"):
            vehicle = vehicle_of(r["Vehicle Plate"])
            assignment_service.assign_vehicle(
                db,
                org.id,
                vehicle.id,
                VehicleAssignRequest(
                    driver_id=driver_of(r["Driver Name"]).id,
                    assigned_at=datetime.combine(xl_date(r["Start Date"]), time(0), tzinfo=PKT),
                    start_odometer=int(r["Start Odometer (km)"]),  # type: ignore[arg-type]
                    # Not in the workbook.
                    take_condition=VehicleCondition.good,
                ),
                admin.id,
            )

        # 6. Operations -----------------------------------------------------------------
        # Fuel first: a fill is dated at the start odometer, so it must precede the trip
        # that advances the vehicle's odometer.
        trip_rows = table(sheets, "Trips")
        first_trip = {str(t["Vehicle Plate"]).strip(): t for t in trip_rows}
        for r in table(sheets, "Fuel Logs"):
            plate = str(r["Vehicle Plate"]).strip()
            vehicle = vehicle_of(plate)
            # The workbook has no date or odometer for fuel logs: use the vehicle's trip
            # day and its current odometer (i.e. filled up before setting off).
            trip = first_trip.get(plate)
            fill_date = xl_datetime(trip["Start Time"]).date() if trip else date.today()
            fuel_service.create_fuel_log(
                db,
                org.id,
                FuelLogCreate(
                    vehicle_id=vehicle.id,
                    driver_id=driver_of(r["Driver"]).id,
                    date=fill_date,
                    odometer_reading=vehicle.current_odometer,
                    liters_filled=Decimal(str(r["Liters"])),
                    price_per_liter=Decimal(str(r["Cost per Liter (PKR)"])),
                    total_cost=Decimal(str(r["Total Cost (PKR)"])),
                    slip_id=text(r["Slip ID"]),
                    po_number=text(r["PO Number"]),
                    fuel_station_name=text(r["Station Name"]),
                    payment_method=text(r["Payment Method"]),
                    card_used=text(r["Card Used"]),
                ),
                created_by=driver_of(r["Driver"]).user_id or admin.id,
            )

        for r in trip_rows:
            trip_service.create_trip(
                db,
                org.id,
                TripLogCreate(
                    driver_id=driver_of(r["Driver"]).id,
                    vehicle_id=vehicle_of(r["Vehicle Plate"]).id,
                    start_time=xl_datetime(r["Start Time"]),
                    end_time=xl_datetime(r["End Time"]),
                    start_odometer=int(r["Start Odometer (km)"]),  # type: ignore[arg-type]
                    end_odometer=int(r["End Odometer (km)"]),  # type: ignore[arg-type]
                ),
                created_by=driver_of(r["Driver"]).user_id or admin.id,
            )

        for r in table(sheets, "Maintenance Logs"):
            vehicle = vehicle_of(r["Vehicle Plate"])
            services: list[ServiceType] = []
            for name in str(r["Service Types (multi-select)"]).split(","):
                service = mapped(SERVICE_MAP, name, "service type")
                if service not in services:
                    services.append(service)
            supplier = text(r["Supplier"])
            if supplier and supplier not in suppliers:
                raise ValueError(f"Maintenance supplier {supplier!r} is not in the Suppliers sheet")
            maintenance_service.create_maintenance_log(
                db,
                org.id,
                MaintenanceLogCreate(
                    vehicle_id=vehicle.id,
                    date=xl_date(r["Date"]),
                    # The workbook has no odometer for the service: use the vehicle's current one.
                    odometer_at_service=vehicle.current_odometer,
                    service_types=services,
                    service_scale=ServiceScale(str(r["Service Scale"]).strip().lower()),
                    driver_id=driver_of(r["Brought In By"]).id,
                    cost=Decimal(str(r["Cost (PKR)"])),
                    # MaintenanceLog has no supplier column; record it in the description.
                    description=f"Serviced at {supplier}: {', '.join(n.strip() for n in str(r['Service Types (multi-select)']).split(','))}"
                    if supplier
                    else None,
                ),
                created_by=admin.id,
            )

        for r in table(sheets, "Incidents"):
            reporter = driver_of(r["Driver"])
            when = datetime.combine(xl_date(r["Date"]), time(0), tzinfo=PKT) + timedelta(
                minutes=round(float(r["Incident Time"]) * 1440)  # type: ignore[arg-type]
            )
            incident_type = mapped(INCIDENT_TYPE_MAP, r["Type"], "incident type")
            incident_service.create_incident(
                db,
                org.id,
                IncidentLogCreate(
                    driver_id=reporter.id,
                    vehicle_id=vehicle_of(r["Vehicle Plate"]).id,
                    incident_type=incident_type,
                    date=when.date(),
                    incident_time=when,
                    severity=mapped(SEVERITY_MAP, r["Severity"], "incident severity"),
                    # The workbook has no description column; the incident type is the summary.
                    description=str(r["Type"]).strip(),
                    location_area=text(r["Location Area"]),
                    remarks=text(r["Remarks"]),
                    attachment_url=text(r["Attachment URL"]),
                ),
                created_by=reporter.user_id or admin.id,
            )

        print(f"Seeded organization '{ORG_NAME}' (login slug: {ORG_SLUG}).")


if __name__ == "__main__":
    seed(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_WORKBOOK)
