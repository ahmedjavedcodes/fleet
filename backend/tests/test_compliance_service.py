import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.organization import Organization
from app.services import compliance_service
from tests.conftest import make_compliance_rule, make_maintenance_log, make_user, make_vehicle

TODAY = date(2026, 9, 18)


@pytest.fixture()
def admin(db_session: Session, organization: Organization):
    return make_user(db_session, organization, role=UserRole.admin)


# --- four states -----------------------------------------------------------------


def test_compliance_status_never_performed(db_session: Session, organization: Organization) -> None:
    vehicle = make_vehicle(db_session, organization, make="Toyota", model="Hilux")
    make_compliance_rule(db_session, organization, interval_km=10000, interval_months=6)

    result = compliance_service.get_vehicle_compliance(db_session, organization.id, vehicle.id)
    assert len(result.items) == 1
    item = result.items[0]
    assert item.status == "never_performed"
    assert item.km_remaining is None
    assert item.days_remaining is None
    assert item.last_service_date is None


def test_compliance_status_compliant(db_session: Session, organization: Organization) -> None:
    vehicle = make_vehicle(db_session, organization, make="Toyota", model="Hilux", current_odometer=1000)
    make_compliance_rule(db_session, organization, interval_km=10000, interval_months=12)
    make_maintenance_log(db_session, organization, vehicle, date=TODAY - timedelta(days=10), odometer_at_service=900)

    result = compliance_service.get_vehicle_compliance(db_session, organization.id, vehicle.id)
    assert result.items[0].status == "compliant"


def test_compliance_status_overdue_by_km(db_session: Session, organization: Organization) -> None:
    vehicle = make_vehicle(db_session, organization, make="Toyota", model="Hilux", current_odometer=11001)
    make_compliance_rule(db_session, organization, interval_km=10000, interval_months=12)
    make_maintenance_log(db_session, organization, vehicle, date=TODAY - timedelta(days=10), odometer_at_service=1000)

    result = compliance_service.get_vehicle_compliance(db_session, organization.id, vehicle.id)
    assert result.items[0].status == "overdue"


def test_compliance_status_overdue_by_date(db_session: Session, organization: Organization) -> None:
    vehicle = make_vehicle(db_session, organization, make="Toyota", model="Hilux", current_odometer=1000)
    make_compliance_rule(db_session, organization, interval_km=100000, interval_months=6)
    make_maintenance_log(db_session, organization, vehicle, date=date(2020, 1, 1), odometer_at_service=900)

    result = compliance_service.get_vehicle_compliance(db_session, organization.id, vehicle.id)
    assert result.items[0].status == "overdue"


def test_compliance_status_due_soon(db_session: Session, organization: Organization) -> None:
    vehicle = make_vehicle(db_session, organization, make="Toyota", model="Hilux", current_odometer=9000)
    make_compliance_rule(db_session, organization, interval_km=10000, interval_months=12)
    make_maintenance_log(db_session, organization, vehicle, date=TODAY - timedelta(days=10), odometer_at_service=1000)

    result = compliance_service.get_vehicle_compliance(db_session, organization.id, vehicle.id)
    assert result.items[0].status == "due_soon"


# --- boundaries (EC-6 / EC-7) ------------------------------------------------------


def test_compliance_due_soon_boundary_exactly_80_percent_km(db_session: Session, organization: Organization) -> None:
    """Exactly at 80% of the km interval -> due_soon (inclusive boundary)."""
    vehicle = make_vehicle(db_session, organization, make="Toyota", model="Hilux", current_odometer=8000)
    make_compliance_rule(db_session, organization, interval_km=10000, interval_months=120)
    make_maintenance_log(db_session, organization, vehicle, date=TODAY - timedelta(days=1), odometer_at_service=0)

    result = compliance_service.get_vehicle_compliance(db_session, organization.id, vehicle.id)
    assert result.items[0].status == "due_soon"


def test_compliance_overdue_boundary_exactly_100_percent_km_is_not_overdue(
    db_session: Session, organization: Organization
) -> None:
    """Exactly at 100% (km_gap == interval_km) -> NOT overdue, only strictly
    greater counts; falls into due_soon since 100% >= 80%."""
    vehicle = make_vehicle(db_session, organization, make="Toyota", model="Hilux", current_odometer=10000)
    make_compliance_rule(db_session, organization, interval_km=10000, interval_months=120)
    make_maintenance_log(db_session, organization, vehicle, date=TODAY - timedelta(days=1), odometer_at_service=0)

    result = compliance_service.get_vehicle_compliance(db_session, organization.id, vehicle.id)
    assert result.items[0].status == "due_soon"


def test_compliance_overdue_boundary_101_percent_km(db_session: Session, organization: Organization) -> None:
    vehicle = make_vehicle(db_session, organization, make="Toyota", model="Hilux", current_odometer=10001)
    make_compliance_rule(db_session, organization, interval_km=10000, interval_months=120)
    make_maintenance_log(db_session, organization, vehicle, date=TODAY - timedelta(days=1), odometer_at_service=0)

    result = compliance_service.get_vehicle_compliance(db_session, organization.id, vehicle.id)
    assert result.items[0].status == "overdue"


def test_compliance_negative_km_gap_is_compliant(db_session: Session, organization: Organization) -> None:
    """A data-entry error (current_odometer below the log's own reading)
    should not crash, and a negative gap is correctly 'compliant'."""
    vehicle = make_vehicle(db_session, organization, make="Toyota", model="Hilux", current_odometer=500)
    make_compliance_rule(db_session, organization, interval_km=10000, interval_months=120)
    make_maintenance_log(db_session, organization, vehicle, date=TODAY - timedelta(days=1), odometer_at_service=1000)

    result = compliance_service.get_vehicle_compliance(db_session, organization.id, vehicle.id)
    assert result.items[0].status == "compliant"


# --- fresh-on-read, no stored status ------------------------------------------------


def test_compliance_fresh_on_every_read(db_session: Session, organization: Organization) -> None:
    vehicle = make_vehicle(db_session, organization, make="Toyota", model="Hilux", current_odometer=1000)
    make_compliance_rule(db_session, organization, interval_km=10000, interval_months=120)
    make_maintenance_log(db_session, organization, vehicle, date=TODAY - timedelta(days=1), odometer_at_service=900)

    first = compliance_service.get_vehicle_compliance(db_session, organization.id, vehicle.id)
    assert first.items[0].status == "compliant"

    vehicle.current_odometer = 20000  # no write to any compliance table
    db_session.commit()

    second = compliance_service.get_vehicle_compliance(db_session, organization.id, vehicle.id)
    assert second.items[0].status == "overdue"


# --- rules scoped by make/model -----------------------------------------------------


def test_rules_scoped_by_make_model_not_vehicle(db_session: Session, organization: Organization) -> None:
    make_compliance_rule(db_session, organization, vehicle_make="Toyota", vehicle_model="Hilux")

    hilux_a = make_vehicle(db_session, organization, make="Toyota", model="Hilux")
    hilux_b = make_vehicle(db_session, organization, make="Toyota", model="Hilux")
    corolla = make_vehicle(db_session, organization, make="Toyota", model="Corolla")

    assert len(compliance_service.get_vehicle_compliance(db_session, organization.id, hilux_a.id).items) == 1
    assert len(compliance_service.get_vehicle_compliance(db_session, organization.id, hilux_b.id).items) == 1
    assert len(compliance_service.get_vehicle_compliance(db_session, organization.id, corolla.id).items) == 0


def test_zero_matching_rules_returns_empty_list(db_session: Session, organization: Organization) -> None:
    vehicle = make_vehicle(db_session, organization, make="Isuzu", model="NPR")
    result = compliance_service.get_vehicle_compliance(db_session, organization.id, vehicle.id)
    assert result.items == []


def test_latest_log_used_for_compliance(db_session: Session, organization: Organization) -> None:
    """Multiple logs of the same service_type -- only the latest by date counts."""
    vehicle = make_vehicle(db_session, organization, make="Toyota", model="Hilux", current_odometer=9500)
    make_compliance_rule(db_session, organization, interval_km=10000, interval_months=120)
    make_maintenance_log(db_session, organization, vehicle, date=date(2020, 1, 1), odometer_at_service=0)
    make_maintenance_log(db_session, organization, vehicle, date=TODAY - timedelta(days=1), odometer_at_service=9000)

    result = compliance_service.get_vehicle_compliance(db_session, organization.id, vehicle.id)
    assert result.items[0].last_service_date == TODAY - timedelta(days=1)
    assert result.items[0].status == "compliant"  # 500 km gap against the latest log, not overdue against the old one


# --- fleet matrix -----------------------------------------------------------------


def test_fleet_compliance_matrix_covers_all_non_retired_vehicles(db_session: Session, organization: Organization) -> None:
    make_compliance_rule(db_session, organization, vehicle_make="Toyota", vehicle_model="Hilux")
    v1 = make_vehicle(db_session, organization, make="Toyota", model="Hilux")
    v2 = make_vehicle(db_session, organization, make="Toyota", model="Hilux")

    matrix = compliance_service.get_fleet_compliance_matrix(db_session, organization.id)
    ids = {v.vehicle_id for v in matrix}
    assert {v1.id, v2.id}.issubset(ids)


def test_org_scoping(db_session: Session, organization: Organization) -> None:
    make_compliance_rule(db_session, organization)

    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()

    assert compliance_service.list_rules(db_session, other_org.id) == []
    assert compliance_service.get_fleet_compliance_matrix(db_session, other_org.id) == []
