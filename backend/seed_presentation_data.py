"""Top up the seeded `fleetops` organization for a demo: fills the dashboard widgets
that seed_dummy_data.py leaves empty.

    python seed_presentation_data.py

Run it once, after seed_dummy_data.py. It refuses to run a second time (it looks
for the fuel slip it creates). What it adds:

  * a second fuel log for AB-1234 at 45,500 km, so cost_per_km is calculated
  * an estimated cost of 15,000 on CD-5678's incident
  * service intervals on two vehicles, one overdue and one due within 500 km
  * compliance rules and shift (driver) reports
  * a few received purchase orders, so supplier reliability and lead time show

Everything goes through the service layer (same invariants as the API) except the
incident cost: the API treats estimated_cost as immutable after creation, so that
one is a direct update, which is exactly what a data fix-up is.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.accountability import IncidentLog
from app.models.driver import Driver
from app.models.enums import ServiceScale, ServiceType, VehicleCondition
from app.models.fuel import FuelLog
from app.models.organization import Organization
from app.models.supplier import Supplier
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.accountability import DriverReportCreate
from app.schemas.compliance import ComplianceRuleCreate
from app.schemas.fuel import FuelLogCreate
from app.schemas.inventory import CompatibleVehicle, PartsInventoryCreate, PurchaseOrderCreate, PurchaseOrderLineItem
from app.schemas.maintenance import MaintenanceLogCreate
from app.services import (
    compliance_service,
    driver_report_service,
    fuel_service,
    inventory_service,
    maintenance_service,
    purchase_order_service,
)

ORG_SLUG = "fleetops"
MARKER_SLIP = "SLP-99045"
SERVICE_INTERVAL_KM = 5000
# The vehicle model stores a service interval in months, not days: 3 months ~ 90 days.
SERVICE_INTERVAL_MONTHS = 3
MECHANIC = "Hassan Raza"


def _by(db: Session, model, org_id: uuid.UUID, **filters):
    row = db.execute(select(model).where(model.organization_id == org_id, *(getattr(model, k) == v for k, v in filters.items()))).scalars().first()
    if row is None:
        raise SystemExit(f"Missing {model.__name__} {filters} -- run seed_dummy_data.py first.")
    return row


def seed() -> None:
    today = datetime.now(timezone.utc).date()
    with SessionLocal() as db:
        org = db.execute(select(Organization).where(Organization.slug == ORG_SLUG)).scalar_one_or_none()
        if org is None:
            raise SystemExit(f"Organization '{ORG_SLUG}' not found -- run seed_dummy_data.py first.")
        if db.execute(select(FuelLog).where(FuelLog.organization_id == org.id, FuelLog.slip_id == MARKER_SLIP)).first():
            raise SystemExit("Presentation data is already seeded -- nothing to do.")

        admin = _by(db, User, org.id, email="admin@fleetops.com")
        vehicle = {v.plate_number: v for v in db.execute(select(Vehicle).where(Vehicle.organization_id == org.id)).scalars()}
        driver = {d.full_name: d for d in db.execute(select(Driver).where(Driver.organization_id == org.id)).scalars()}
        user_of = {d.full_name: d.user_id for d in driver.values()}
        summary: list[str] = []

        # 1. Second fuel log on AB-1234 -> cost_per_km = total_cost / (45,500 - 45,000) ----
        ab = vehicle["AB-1234"]
        previous = db.execute(
            select(FuelLog).where(FuelLog.vehicle_id == ab.id).order_by(FuelLog.odometer_reading.desc())
        ).scalars().first()
        assert previous is not None and previous.odometer_reading == 45_000, "expected the seeded 45,000 km fill on AB-1234"
        fill = fuel_service.create_fuel_log(
            db,
            org.id,
            FuelLogCreate(
                vehicle_id=ab.id,
                driver_id=driver["Ali Khan"].id,
                date=today,
                odometer_reading=45_500,
                liters_filled=Decimal("60"),
                price_per_liter=Decimal("280"),
                total_cost=Decimal("16800"),
                slip_id=MARKER_SLIP,
                po_number="PO-2026-A2",
                fuel_station_name="Shell DHA Phase 5",
                payment_method="Corporate Card",
                card_used="Visa ****4321",
            ),
            created_by=user_of["Ali Khan"] or admin.id,
        )
        summary.append(f"fuel AB-1234 @45,500 km -> cost_per_km {fill.cost_per_km}")

        # 2. Incident estimated cost --------------------------------------------------
        incident = db.execute(
            select(IncidentLog)
            .where(IncidentLog.organization_id == org.id, IncidentLog.vehicle_id == vehicle["CD-5678"].id)
            .order_by(IncidentLog.created_at)
        ).scalars().first()
        if incident is None:
            raise SystemExit("No incident on CD-5678 -- run seed_dummy_data.py first.")
        incident.estimated_cost = Decimal("15000")
        incident.updated_by = admin.id
        db.commit()
        summary.append("incident CD-5678 estimated_cost 15,000")

        # 3. Service intervals + one overdue and one upcoming vehicle -----------------
        # Intervals go on first: create_maintenance_log freezes next_due_* from them.
        overdue_v, upcoming_v = vehicle["GH-3456"], vehicle["IJ-7890"]
        for v in (overdue_v, upcoming_v):
            v.service_interval_km = SERVICE_INTERVAL_KM
            v.service_interval_months = SERVICE_INTERVAL_MONTHS
            v.updated_by = admin.id
        db.commit()

        # Overdue: serviced 6,000 km ago (limit 5,000) and 200 days ago (limit ~90).
        maintenance_service.create_maintenance_log(
            db,
            org.id,
            MaintenanceLogCreate(
                vehicle_id=overdue_v.id,
                date=today - timedelta(days=200),
                odometer_at_service=overdue_v.current_odometer - 6000,
                service_types=[ServiceType.oil_change],
                service_scale=ServiceScale.minor,
                driver_id=driver["Saad Tariq"].id,
                cost=Decimal("8500"),
                mechanic_name=MECHANIC,
                description="Oil and filter change",
            ),
            admin.id,
        )
        # Upcoming: due at +500 km, and its date is still ~7 weeks away.
        maintenance_service.create_maintenance_log(
            db,
            org.id,
            MaintenanceLogCreate(
                vehicle_id=upcoming_v.id,
                date=today - timedelta(days=41),
                odometer_at_service=upcoming_v.current_odometer - (SERVICE_INTERVAL_KM - 500),
                service_types=[ServiceType.oil_change],
                service_scale=ServiceScale.minor,
                driver_id=driver["Omer Farooq"].id,
                cost=Decimal("7200"),
                mechanic_name=MECHANIC,
                description="Oil and filter change",
            ),
            admin.id,
        )
        overdue = maintenance_service.list_overdue(db, org.id)
        upcoming = maintenance_service.list_upcoming(db, org.id)
        assert any(i.vehicle_id == overdue_v.id for i in overdue), "GH-3456 should be overdue"
        assert any(i.vehicle_id == upcoming_v.id for i in upcoming), "IJ-7890 should be upcoming"
        summary.append(f"maintenance: GH-3456 overdue, IJ-7890 due in 500 km ({len(overdue)} overdue, {len(upcoming)} upcoming)")

        # 4. Compliance rules (manufacturer schedules, matched by make/model) ---------
        rules = [
            ("Isuzu", "D-Max", ServiceType.oil_change, 5000, 3, "Engine oil and filter change"),
            ("Toyota", "Hiace", ServiceType.oil_change, 5000, 3, "Engine oil and filter change"),
            ("Toyota", "Hilux", ServiceType.general_inspection, 20000, 12, "Annual safety inspection: brakes, lights, steering and tyres"),
            ("Ford", "Transit", ServiceType.other, 15000, 12, "Annual emissions test"),
        ]
        for make, model, service_type, km, months, description in rules:
            compliance_service.create_rule(
                db,
                org.id,
                ComplianceRuleCreate(
                    vehicle_make=make, vehicle_model=model, service_type=service_type, interval_km=km, interval_months=months, description=description
                ),
                admin.id,
            )
        summary.append(f"{len(rules)} compliance rules")

        # 5. Shift (driver) reports ---------------------------------------------------
        reports = [
            ("Ali Khan", "AB-1234", today - timedelta(days=1), VehicleCondition.good, "Handed over with a full tank, no issues.", None),
            ("Bilal Ahmed", "CD-5678", today - timedelta(days=1), VehicleCondition.fair, "Left bumper scraped, see the incident report.", "Scraped left bumper on a guardrail near Ravi Toll Plaza."),
            ("Omer Farooq", "EF-9012", today, VehicleCondition.fair, "Vehicle returned clean.", "Steering feels heavy at low speed; check power steering fluid."),
            ("Ali Khan", "AB-1234", today, VehicleCondition.good, "Fuelled at Shell DHA Phase 5 before handover.", None),
        ]
        for name, plate, shift_date, condition, notes, issues in reports:
            driver_report_service.create_driver_report(
                db,
                org.id,
                DriverReportCreate(
                    driver_id=driver[name].id, vehicle_id=vehicle[plate].id, shift_date=shift_date, vehicle_condition=condition, handover_notes=notes, issues_reported=issues
                ),
                created_by=user_of[name] or admin.id,
            )
        summary.append(f"{len(reports)} shift reports")

        # 6. Parts + received purchase orders -> supplier reliability / lead time -----
        def part(number: str, name: str, category: str, make: str, model: str, qty: int, threshold: int, cost: str):
            return inventory_service.create_part(
                db,
                org.id,
                PartsInventoryCreate(
                    part_number=number,
                    name=name,
                    category=category,
                    compatible_vehicles=[CompatibleVehicle(make=make, model=model)],
                    qty_on_hand=qty,
                    reorder_threshold=threshold,
                    unit_cost=Decimal(cost),
                ),
                admin.id,
            )

        filter_part = part("HL-OIL-F01", "Oil filter", "filters", "Toyota", "Hilux", 20, 8, "850")
        pads_part = part("TR-BRK-P02", "Brake pads (front set)", "brakes", "Ford", "Transit", 3, 6, "6400")  # below threshold: low-stock alert
        tyre_part = part("HL-TYR-265", "Tyre 265/65 R17", "tyres", "Toyota", "Hilux", 8, 4, "31500")

        supplier = {s.name: s for s in db.execute(select(Supplier).where(Supplier.organization_id == org.id)).scalars()}

        def receive(supplier_name: str, ordered_days_ago: int, expected_in_days: int, part_row, qty: int) -> None:
            order = purchase_order_service.create_purchase_order(
                db,
                org.id,
                PurchaseOrderCreate(
                    supplier_id=supplier[supplier_name].id,
                    order_date=today - timedelta(days=ordered_days_ago),
                    expected_delivery=today + timedelta(days=expected_in_days),
                    line_items=[PurchaseOrderLineItem(part_id=part_row.id, qty=qty, unit_price=part_row.unit_cost)],
                ),
                admin.id,
            )
            purchase_order_service.receive_purchase_order(db, org.id, order.id, admin.id)

        # receive_purchase_order stamps actual_delivery = today, so "late" means expected in the past.
        receive("Global Auto Parts", 5, 2, filter_part, 10)   # on time, 5-day lead
        receive("Global Auto Parts", 9, -2, pads_part, 4)     # late, 9-day lead
        receive("Michelin City", 3, 0, tyre_part, 4)          # on time, 3-day lead
        # One order still in flight, so the purchase-order list has an open item.
        purchase_order_service.create_purchase_order(
            db,
            org.id,
            PurchaseOrderCreate(
                supplier_id=supplier["Global Auto Parts"].id,
                order_date=today - timedelta(days=1),
                expected_delivery=today + timedelta(days=6),
                line_items=[PurchaseOrderLineItem(part_id=pads_part.id, qty=6, unit_price=pads_part.unit_cost)],
            ),
            admin.id,
        )
        for s in db.execute(select(Supplier).where(Supplier.organization_id == org.id).order_by(Supplier.name)).scalars():
            db.refresh(s)
            summary.append(f"supplier {s.name}: reliability {s.reliability_score}, avg lead time {s.avg_lead_time_days}")

        print("Seeded presentation data for 'fleetops':")
        for line in summary:
            print("  -", line)


if __name__ == "__main__":
    seed()
