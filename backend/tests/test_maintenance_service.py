import uuid
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.enums import ServiceType, UserRole
from app.models.organization import Organization
from app.schemas.maintenance import MaintenanceLogCreate, MaintenanceLogUpdate, MechanicReportCreate, PartUsed
from app.services import maintenance_service
from tests.conftest import make_maintenance_log, make_part, make_user, make_vehicle

BASE_DATE = date(2026, 6, 1)


@pytest.fixture()
def admin(db_session: Session, organization: Organization):
    return make_user(db_session, organization, role=UserRole.admin)


# --- next_due computation -----------------------------------------------------


def test_next_due_computed_on_create(db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization, service_interval_km=10000, service_interval_months=6)
    data = MaintenanceLogCreate(
        vehicle_id=vehicle.id, date=BASE_DATE, odometer_at_service=5000, service_type=ServiceType.oil_change
    )
    log = maintenance_service.create_maintenance_log(db_session, organization.id, data, admin.id)
    assert log.next_due_km == 15000
    assert log.next_due_date == date(2026, 12, 1)


def test_next_due_null_when_vehicle_has_no_interval_configured(db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization, service_interval_km=None, service_interval_months=None)
    data = MaintenanceLogCreate(
        vehicle_id=vehicle.id, date=BASE_DATE, odometer_at_service=5000, service_type=ServiceType.oil_change
    )
    log = maintenance_service.create_maintenance_log(db_session, organization.id, data, admin.id)
    assert log.next_due_km is None
    assert log.next_due_date is None


def test_next_due_km_only_configured(db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization, service_interval_km=10000, service_interval_months=None)
    data = MaintenanceLogCreate(
        vehicle_id=vehicle.id, date=BASE_DATE, odometer_at_service=5000, service_type=ServiceType.oil_change
    )
    log = maintenance_service.create_maintenance_log(db_session, organization.id, data, admin.id)
    assert log.next_due_km == 15000
    assert log.next_due_date is None


def test_vehicle_not_found_returns_404(db_session: Session, organization: Organization, admin) -> None:
    data = MaintenanceLogCreate(
        vehicle_id=uuid.uuid4(), date=BASE_DATE, odometer_at_service=5000, service_type=ServiceType.oil_change
    )
    with pytest.raises(HTTPException) as exc_info:
        maintenance_service.create_maintenance_log(db_session, organization.id, data, admin.id)
    assert exc_info.value.status_code == 404


def test_next_due_recomputed_on_update_when_odometer_changes(db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization, service_interval_km=10000, service_interval_months=6)
    log = make_maintenance_log(db_session, organization, vehicle, odometer_at_service=5000, next_due_km=15000)

    updated = maintenance_service.update_maintenance_log(
        db_session, organization.id, log.id, MaintenanceLogUpdate(odometer_at_service=6000), admin.id
    )
    assert updated.next_due_km == 16000


def test_next_due_recomputed_using_current_vehicle_intervals(db_session: Session, organization: Organization, admin) -> None:
    """Unlike FuelLog, maintenance logs are allowed to reflect updated vehicle
    intervals on edit -- no freeze-on-edit rule."""
    vehicle = make_vehicle(db_session, organization, service_interval_km=10000, service_interval_months=6)
    log = make_maintenance_log(db_session, organization, vehicle, odometer_at_service=5000, next_due_km=15000)

    vehicle.service_interval_km = 20000
    db_session.commit()

    updated = maintenance_service.update_maintenance_log(
        db_session, organization.id, log.id, MaintenanceLogUpdate(odometer_at_service=5000), admin.id
    )
    assert updated.next_due_km == 25000  # 5000 + the NEW interval (20000), not the original


def test_next_due_not_recomputed_on_unrelated_update(db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization, service_interval_km=10000, service_interval_months=6)
    log = make_maintenance_log(db_session, organization, vehicle, odometer_at_service=5000, next_due_km=15000, next_due_date=date(2026, 12, 1))

    updated = maintenance_service.update_maintenance_log(
        db_session, organization.id, log.id, MaintenanceLogUpdate(cost="500.00"), admin.id
    )
    assert updated.next_due_km == 15000
    assert updated.next_due_date == date(2026, 12, 1)


# --- mechanic report + stock decrement (spans Plan 02) -------------------------


def test_mechanic_report_decrements_stock(db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization)
    log = make_maintenance_log(db_session, organization, vehicle)
    part = make_part(db_session, organization, qty_on_hand=10, reorder_threshold=5)

    report, alerts = maintenance_service.create_mechanic_report(
        db_session,
        organization.id,
        log.id,
        MechanicReportCreate(diagnostic_notes="Worn belt", parts_used=[PartUsed(part_id=part.id, qty=6)]),
        admin.id,
    )
    assert report.parts_used == [{"part_id": str(part.id), "qty": 6}]
    # parts_used is built via model_dump(mode="json"), so part_id is a string
    # by the time it reaches the alert dict too, not a UUID object.
    assert alerts == [{"part_id": str(part.id), "low_stock_alert": True}]
    assert part.qty_on_hand == 4  # same identity-mapped object, mutated in place


def test_mechanic_report_rejects_duplicate(db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization)
    log = make_maintenance_log(db_session, organization, vehicle)

    maintenance_service.create_mechanic_report(db_session, organization.id, log.id, MechanicReportCreate(), admin.id)
    with pytest.raises(HTTPException) as exc_info:
        maintenance_service.create_mechanic_report(db_session, organization.id, log.id, MechanicReportCreate(), admin.id)
    assert exc_info.value.status_code == 409


def test_mechanic_report_insufficient_stock_rolls_back(db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization)
    log = make_maintenance_log(db_session, organization, vehicle)
    part = make_part(db_session, organization, qty_on_hand=2)

    with pytest.raises(HTTPException) as exc_info:
        maintenance_service.create_mechanic_report(
            db_session,
            organization.id,
            log.id,
            MechanicReportCreate(parts_used=[PartUsed(part_id=part.id, qty=10)]),
            admin.id,
        )
    assert exc_info.value.status_code == 400
    assert part.qty_on_hand == 2  # unchanged -- report insert never committed either

    # The report INSERT was flushed (autoflush, ahead of decrement's own SELECT)
    # but never committed. In production, FastAPI's get_db() dependency closes
    # the session in a `finally` after the exception propagates, and Session.close()
    # rolls back any uncommitted transaction -- here we do that same rollback
    # explicitly before re-querying, since we're calling the service directly.
    db_session.rollback()

    from sqlalchemy import select

    from app.models.maintenance import MechanicReport

    remaining = db_session.execute(
        select(MechanicReport).where(MechanicReport.maintenance_log_id == log.id)
    ).scalar_one_or_none()
    assert remaining is None


# --- upcoming / overdue ---------------------------------------------------------


def test_upcoming_window_boundary(db_session: Session, organization: Organization) -> None:
    vehicle_999 = make_vehicle(db_session, organization, current_odometer=9001)
    vehicle_1000 = make_vehicle(db_session, organization, current_odometer=9000)
    vehicle_1001 = make_vehicle(db_session, organization, current_odometer=8999)
    for v in (vehicle_999, vehicle_1000, vehicle_1001):
        make_maintenance_log(db_session, organization, v, odometer_at_service=v.current_odometer, next_due_km=10000)

    items = maintenance_service.list_upcoming(db_session, organization.id, window_km=1000)
    ids = {item.vehicle_id for item in items}
    assert vehicle_999.id in ids  # 999 remaining -- inside window
    assert vehicle_1000.id not in ids  # exactly 1000 -- excluded (< window_km, not <=)
    assert vehicle_1001.id not in ids  # 1001 remaining -- outside window


def test_upcoming_excludes_already_overdue(db_session: Session, organization: Organization) -> None:
    vehicle = make_vehicle(db_session, organization, current_odometer=11000)
    make_maintenance_log(db_session, organization, vehicle, odometer_at_service=5000, next_due_km=10000)
    items = maintenance_service.list_upcoming(db_session, organization.id, window_km=1000)
    assert items == []  # already past due -- km_remaining is negative, not "upcoming"


def test_overdue_by_km(db_session: Session, organization: Organization) -> None:
    vehicle = make_vehicle(db_session, organization, current_odometer=15001)
    make_maintenance_log(db_session, organization, vehicle, odometer_at_service=5000, next_due_km=15000, next_due_date=date(2030, 1, 1))
    items = maintenance_service.list_overdue(db_session, organization.id)
    assert any(item.vehicle_id == vehicle.id for item in items)


def test_overdue_by_date(db_session: Session, organization: Organization) -> None:
    vehicle = make_vehicle(db_session, organization, current_odometer=100)
    make_maintenance_log(db_session, organization, vehicle, odometer_at_service=50, next_due_km=100000, next_due_date=date(2020, 1, 1))
    items = maintenance_service.list_overdue(db_session, organization.id)
    assert any(item.vehicle_id == vehicle.id for item in items)


def test_overdue_uses_latest_log_only(db_session: Session, organization: Organization) -> None:
    vehicle = make_vehicle(db_session, organization, current_odometer=16000)
    # Superseded older log: would flag overdue on its own, but a newer log of
    # the same service_type exists and must win.
    make_maintenance_log(
        db_session, organization, vehicle,
        date=date(2026, 1, 1), odometer_at_service=1000, next_due_km=5000, next_due_date=date(2030, 1, 1),
    )
    make_maintenance_log(
        db_session, organization, vehicle,
        date=date(2026, 6, 1), odometer_at_service=15000, next_due_km=25000, next_due_date=date(2030, 1, 1),
    )
    items = maintenance_service.list_overdue(db_session, organization.id)
    assert not any(item.vehicle_id == vehicle.id for item in items)


def test_org_scoping(db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization)
    make_maintenance_log(db_session, organization, vehicle)

    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()

    assert maintenance_service.list_maintenance_logs(db_session, other_org.id) == []
    assert maintenance_service.list_upcoming(db_session, other_org.id) == []
    assert maintenance_service.list_overdue(db_session, other_org.id) == []
