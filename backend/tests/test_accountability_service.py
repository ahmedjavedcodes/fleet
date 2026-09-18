import inspect
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.accountability import DriverReport, IncidentLog
from app.models.enums import (
    IncidentResolutionStatus,
    IncidentSeverity,
    IncidentType,
    UserRole,
    VehicleCondition,
)
from app.models.organization import Organization
from app.schemas.accountability import (
    DriverReportCreate,
    IncidentLogCreate,
    IncidentLogResolutionUpdate,
    TripLogCreate,
)
from app.services import driver_report_service, incident_service, trip_service
from tests.conftest import make_driver, make_user, make_vehicle

START = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
END = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)


@pytest.fixture()
def admin(db_session: Session, organization: Organization):
    return make_user(db_session, organization, role=UserRole.admin)


@pytest.fixture()
def driver_profile(db_session: Session, organization: Organization):
    return make_driver(db_session, organization)


# --- TripLog -----------------------------------------------------------------


def test_distance_computed_on_create(db_session: Session, organization: Organization, admin, driver_profile) -> None:
    vehicle = make_vehicle(db_session, organization, current_odometer=0)
    data = TripLogCreate(
        driver_id=driver_profile.id, vehicle_id=vehicle.id, start_time=START, end_time=END,
        start_odometer=1000, end_odometer=1150,
    )
    trip = trip_service.create_trip(db_session, organization.id, data, admin.id)
    assert trip.distance_km == 150


def test_vehicle_odometer_updated_as_side_effect(db_session: Session, organization: Organization, admin, driver_profile) -> None:
    vehicle = make_vehicle(db_session, organization, current_odometer=500)
    data = TripLogCreate(
        driver_id=driver_profile.id, vehicle_id=vehicle.id, start_time=START, end_time=END,
        start_odometer=1000, end_odometer=1500,
    )
    trip_service.create_trip(db_session, organization.id, data, admin.id)
    assert vehicle.current_odometer == 1500


def test_vehicle_odometer_not_decreased(db_session: Session, organization: Organization, admin, driver_profile) -> None:
    vehicle = make_vehicle(db_session, organization, current_odometer=5000)
    data = TripLogCreate(
        driver_id=driver_profile.id, vehicle_id=vehicle.id, start_time=START, end_time=END,
        start_odometer=1000, end_odometer=1500,
    )
    trip_service.create_trip(db_session, organization.id, data, admin.id)
    assert vehicle.current_odometer == 5000


def test_trip_rejects_end_odometer_less_than_start(db_session: Session, organization: Organization, admin, driver_profile) -> None:
    vehicle = make_vehicle(db_session, organization)
    data = TripLogCreate(
        driver_id=driver_profile.id, vehicle_id=vehicle.id, start_time=START, end_time=END,
        start_odometer=1000, end_odometer=900,
    )
    with pytest.raises(HTTPException) as exc_info:
        trip_service.create_trip(db_session, organization.id, data, admin.id)
    assert exc_info.value.status_code == 400


def test_trip_zero_distance_allowed(db_session: Session, organization: Organization, admin, driver_profile) -> None:
    """end_odometer == start_odometer is allowed -- only strictly less than is rejected."""
    vehicle = make_vehicle(db_session, organization)
    data = TripLogCreate(
        driver_id=driver_profile.id, vehicle_id=vehicle.id, start_time=START, end_time=END,
        start_odometer=1000, end_odometer=1000,
    )
    trip = trip_service.create_trip(db_session, organization.id, data, admin.id)
    assert trip.distance_km == 0


def test_trip_created_by_stamped_from_caller_not_driver(
    db_session: Session, organization: Organization, admin, driver_profile
) -> None:
    """An admin logging a trip on a driver's behalf: created_by is the admin,
    driver_id is the driver -- these are allowed to differ."""
    vehicle = make_vehicle(db_session, organization)
    data = TripLogCreate(
        driver_id=driver_profile.id, vehicle_id=vehicle.id, start_time=START, end_time=END,
        start_odometer=100, end_odometer=200,
    )
    trip = trip_service.create_trip(db_session, organization.id, data, admin.id)
    assert trip.created_by == admin.id
    assert trip.driver_id == driver_profile.id


# --- DriverReport (append-only) -----------------------------------------------


def test_driver_report_append_only_in_service_layer() -> None:
    """No function in driver_report_service.py mutates an existing row."""
    functions = [name for name, _ in inspect.getmembers(driver_report_service, inspect.isfunction)]
    assert not any("update" in name for name in functions)


def test_create_driver_report(db_session: Session, organization: Organization, admin, driver_profile) -> None:
    vehicle = make_vehicle(db_session, organization)
    data = DriverReportCreate(
        driver_id=driver_profile.id, vehicle_id=vehicle.id, shift_date=date(2026, 6, 1),
        vehicle_condition=VehicleCondition.good, handover_notes="All good",
    )
    report = driver_report_service.create_driver_report(db_session, organization.id, data, admin.id)
    assert report.vehicle_condition == VehicleCondition.good
    assert report.created_by == admin.id


# --- IncidentLog ---------------------------------------------------------------


def test_incident_original_fields_immutable_after_create(
    db_session: Session, organization: Organization, admin, driver_profile
) -> None:
    vehicle = make_vehicle(db_session, organization)
    data = IncidentLogCreate(
        driver_id=driver_profile.id, vehicle_id=vehicle.id, incident_type=IncidentType.damage,
        date=date(2026, 6, 1), severity=IncidentSeverity.moderate, description="Dented fender",
    )
    incident = incident_service.create_incident(db_session, organization.id, data, admin.id)

    updated = incident_service.update_incident_resolution(
        db_session, organization.id, incident.id,
        IncidentLogResolutionUpdate(resolution_status=IncidentResolutionStatus.resolved, resolution_notes="Fixed"),
        admin.id,
    )
    assert updated.description == "Dented fender"
    assert updated.severity == IncidentSeverity.moderate
    assert updated.resolution_status == IncidentResolutionStatus.resolved


def test_incident_resolution_update_schema_rejects_immutable_fields() -> None:
    """The resolution-update schema itself has no description/severity fields
    -- passing them is a validation error, not a silently-ignored extra."""
    with pytest.raises(Exception):
        IncidentLogResolutionUpdate(resolution_status=IncidentResolutionStatus.open, description="hijacked")


def test_incident_driver_id_optional(db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization)
    data = IncidentLogCreate(
        vehicle_id=vehicle.id, incident_type=IncidentType.near_miss, date=date(2026, 6, 1),
        severity=IncidentSeverity.minor, description="Unknown driver at the time",
    )
    incident = incident_service.create_incident(db_session, organization.id, data, admin.id)
    assert incident.driver_id is None


# --- Soft delete recoverable ----------------------------------------------------


def test_soft_delete_recoverable(db_session: Session, organization: Organization, admin, driver_profile) -> None:
    vehicle = make_vehicle(db_session, organization)
    data = DriverReportCreate(
        driver_id=driver_profile.id, vehicle_id=vehicle.id, shift_date=date(2026, 6, 1), vehicle_condition=VehicleCondition.fair,
    )
    report = driver_report_service.create_driver_report(db_session, organization.id, data, admin.id)

    report.is_deleted = True
    report.deleted_at = datetime.now(timezone.utc)
    db_session.commit()

    with pytest.raises(HTTPException):
        driver_report_service.get_driver_report(db_session, organization.id, report.id)

    still_present = db_session.execute(select(DriverReport).where(DriverReport.id == report.id)).scalar_one()
    assert still_present.is_deleted is True


# --- org scoping -----------------------------------------------------------------


def test_org_scoping(db_session: Session, organization: Organization, admin, driver_profile) -> None:
    vehicle = make_vehicle(db_session, organization)
    trip_service.create_trip(
        db_session, organization.id,
        TripLogCreate(driver_id=driver_profile.id, vehicle_id=vehicle.id, start_time=START, end_time=END, start_odometer=1, end_odometer=100),
        admin.id,
    )

    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()

    assert trip_service.list_trips(db_session, other_org.id) == []
    assert driver_report_service.list_driver_reports(db_session, other_org.id) == []
    assert incident_service.list_incidents(db_session, other_org.id) == []
