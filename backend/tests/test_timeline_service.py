import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.models.enums import IncidentSeverity, IncidentType, UserRole, VehicleCondition
from app.models.organization import Organization
from app.schemas.accountability import DriverReportCreate, IncidentLogCreate, TripLogCreate
from app.services import driver_report_service, incident_service, timeline_service, trip_service
from tests.conftest import make_driver, make_user, make_vehicle


@pytest.fixture()
def admin(db_session: Session, organization: Organization):
    return make_user(db_session, organization, role=UserRole.admin)


@pytest.fixture()
def driver_profile(db_session: Session, organization: Organization):
    return make_driver(db_session, organization)


def test_timeline_interleaves_and_orders_correctly(
    db_session: Session, organization: Organization, admin, driver_profile
) -> None:
    vehicle = make_vehicle(db_session, organization)

    trip = trip_service.create_trip(
        db_session, organization.id,
        TripLogCreate(
            driver_id=driver_profile.id, vehicle_id=vehicle.id,
            start_time=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc), end_time=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            start_odometer=1000, end_odometer=1100,
        ),
        admin.id,
    )
    report = driver_report_service.create_driver_report(
        db_session, organization.id,
        DriverReportCreate(driver_id=driver_profile.id, vehicle_id=vehicle.id, shift_date=date(2026, 6, 2), vehicle_condition=VehicleCondition.good),
        admin.id,
    )
    incident = incident_service.create_incident(
        db_session, organization.id,
        IncidentLogCreate(driver_id=driver_profile.id, vehicle_id=vehicle.id, incident_type=IncidentType.damage, date=date(2026, 6, 3), severity=IncidentSeverity.moderate, description="Bumper damage"),
        admin.id,
    )

    timeline = timeline_service.get_vehicle_timeline(db_session, organization.id, vehicle.id)
    assert [entry.record_type for entry in timeline] == ["incident", "report", "trip"]  # date descending
    assert timeline[0].id == incident.id
    assert timeline[1].id == report.id
    assert timeline[2].id == trip.id
    assert timeline[0].summary["description"] == "Bumper damage"
    assert timeline[2].summary["distance_km"] == 100


def test_timeline_summary_decimal_fields_serialize_as_strings(
    db_session: Session, organization: Organization, admin, driver_profile
) -> None:
    """jsonb_build_object renders a bare Decimal column as a JSON number,
    breaking the Decimal-as-string convention every other endpoint follows —
    regression test for the explicit ::text cast in _build_timeline_query."""
    vehicle = make_vehicle(db_session, organization)

    trip = trip_service.create_trip(
        db_session, organization.id,
        TripLogCreate(
            driver_id=driver_profile.id, vehicle_id=vehicle.id,
            start_time=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc), end_time=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            start_odometer=1000, end_odometer=1100, fuel_consumed="8.50",
        ),
        admin.id,
    )
    incident_service.create_incident(
        db_session, organization.id,
        IncidentLogCreate(
            driver_id=driver_profile.id, vehicle_id=vehicle.id, incident_type=IncidentType.damage,
            date=date(2026, 6, 3), severity=IncidentSeverity.moderate, description="Bumper damage",
            estimated_cost="5000.00",
        ),
        admin.id,
    )

    timeline = timeline_service.get_vehicle_timeline(db_session, organization.id, vehicle.id)
    trip_entry = next(e for e in timeline if e.id == trip.id)
    incident_entry = next(e for e in timeline if e.record_type == "incident")
    assert isinstance(trip_entry.summary["fuel_consumed"], str)
    assert trip_entry.summary["fuel_consumed"] == "8.50"
    assert isinstance(incident_entry.summary["estimated_cost"], str)
    assert incident_entry.summary["estimated_cost"] == "5000.00"


def test_timeline_same_date_ordering_is_stable(db_session: Session, organization: Organization, admin, driver_profile) -> None:
    vehicle = make_vehicle(db_session, organization)
    same_date = date(2026, 6, 1)
    report_a = driver_report_service.create_driver_report(
        db_session, organization.id,
        DriverReportCreate(driver_id=driver_profile.id, vehicle_id=vehicle.id, shift_date=same_date, vehicle_condition=VehicleCondition.good),
        admin.id,
    )
    report_b = driver_report_service.create_driver_report(
        db_session, organization.id,
        DriverReportCreate(driver_id=driver_profile.id, vehicle_id=vehicle.id, shift_date=same_date, vehicle_condition=VehicleCondition.fair),
        admin.id,
    )

    first_call = timeline_service.get_vehicle_timeline(db_session, organization.id, vehicle.id)
    second_call = timeline_service.get_vehicle_timeline(db_session, organization.id, vehicle.id)
    assert [e.id for e in first_call] == [e.id for e in second_call]
    assert {report_a.id, report_b.id} == {e.id for e in first_call}


def test_timeline_scoped_to_single_vehicle(db_session: Session, organization: Organization, admin, driver_profile) -> None:
    vehicle_a = make_vehicle(db_session, organization)
    vehicle_b = make_vehicle(db_session, organization)
    driver_report_service.create_driver_report(
        db_session, organization.id,
        DriverReportCreate(driver_id=driver_profile.id, vehicle_id=vehicle_a.id, shift_date=date(2026, 6, 1), vehicle_condition=VehicleCondition.good),
        admin.id,
    )
    driver_report_service.create_driver_report(
        db_session, organization.id,
        DriverReportCreate(driver_id=driver_profile.id, vehicle_id=vehicle_b.id, shift_date=date(2026, 6, 1), vehicle_condition=VehicleCondition.poor),
        admin.id,
    )

    timeline = timeline_service.get_vehicle_timeline(db_session, organization.id, vehicle_a.id)
    assert len(timeline) == 1
    assert timeline[0].summary["vehicle_id"] == str(vehicle_a.id)


def test_timeline_scoped_to_single_driver(db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization)
    driver_a = make_driver(db_session, organization)
    driver_b = make_driver(db_session, organization)
    driver_report_service.create_driver_report(
        db_session, organization.id,
        DriverReportCreate(driver_id=driver_a.id, vehicle_id=vehicle.id, shift_date=date(2026, 6, 1), vehicle_condition=VehicleCondition.good),
        admin.id,
    )
    driver_report_service.create_driver_report(
        db_session, organization.id,
        DriverReportCreate(driver_id=driver_b.id, vehicle_id=vehicle.id, shift_date=date(2026, 6, 1), vehicle_condition=VehicleCondition.poor),
        admin.id,
    )

    timeline = timeline_service.get_driver_timeline(db_session, organization.id, driver_a.id)
    assert len(timeline) == 1
    assert timeline[0].summary["driver_id"] == str(driver_a.id)


def test_timeline_empty_for_vehicle_with_no_records(db_session: Session, organization: Organization) -> None:
    vehicle = make_vehicle(db_session, organization)
    assert timeline_service.get_vehicle_timeline(db_session, organization.id, vehicle.id) == []


def test_timeline_org_scoping(db_session: Session, organization: Organization, admin, driver_profile) -> None:
    vehicle = make_vehicle(db_session, organization)
    driver_report_service.create_driver_report(
        db_session, organization.id,
        DriverReportCreate(driver_id=driver_profile.id, vehicle_id=vehicle.id, shift_date=date(2026, 6, 1), vehicle_condition=VehicleCondition.good),
        admin.id,
    )

    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()

    assert timeline_service.get_vehicle_timeline(db_session, other_org.id, vehicle.id) == []


def test_timeline_entries_carry_vehicle_identity_and_trip_odometers(
    db_session: Session, organization: Organization, admin, driver_profile
) -> None:
    vehicle = make_vehicle(db_session, organization, plate_number="LEA-1234", make="Toyota", model="Hilux")
    trip_service.create_trip(
        db_session, organization.id,
        TripLogCreate(
            driver_id=driver_profile.id, vehicle_id=vehicle.id,
            start_time=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc), end_time=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            start_odometer=45000, end_odometer=45250,
        ),
        admin.id,
    )
    driver_report_service.create_driver_report(
        db_session, organization.id,
        DriverReportCreate(driver_id=driver_profile.id, vehicle_id=vehicle.id, shift_date=date(2026, 6, 2), vehicle_condition=VehicleCondition.good),
        admin.id,
    )
    incident_service.create_incident(
        db_session, organization.id,
        IncidentLogCreate(driver_id=driver_profile.id, vehicle_id=vehicle.id, incident_type=IncidentType.damage, date=date(2026, 6, 3), severity=IncidentSeverity.minor, description="Scratch"),
        admin.id,
    )

    timeline = timeline_service.get_driver_timeline(db_session, organization.id, driver_profile.id)
    assert {e.record_type for e in timeline} == {"trip", "report", "incident"}
    for entry in timeline:
        assert entry.summary["vehicle_plate"] == "LEA-1234"
        assert entry.summary["vehicle_name"] == "Toyota Hilux"
    trip_entry = next(e for e in timeline if e.record_type == "trip")
    assert (trip_entry.summary["start_odometer"], trip_entry.summary["end_odometer"]) == (45000, 45250)


def test_timeline_odometer_snapshot_uses_last_trip_at_or_before_the_event(
    db_session: Session, organization: Organization, admin, driver_profile
) -> None:
    vehicle = make_vehicle(db_session, organization)

    def _trip(day: int, start: int, end: int) -> None:
        trip_service.create_trip(
            db_session, organization.id,
            TripLogCreate(
                driver_id=driver_profile.id, vehicle_id=vehicle.id,
                start_time=datetime(2026, 6, day, 9, 0, tzinfo=timezone.utc), end_time=datetime(2026, 6, day, 12, 0, tzinfo=timezone.utc),
                start_odometer=start, end_odometer=end,
            ),
            admin.id,
        )

    def _report(day: int):
        return driver_report_service.create_driver_report(
            db_session, organization.id,
            DriverReportCreate(driver_id=driver_profile.id, vehicle_id=vehicle.id, shift_date=date(2026, 6, day), vehicle_condition=VehicleCondition.good),
            admin.id,
        )

    before_any_trip = _report(1)  # no trip has ended by the end of 1 June
    _trip(2, 1000, 1100)
    same_day = _report(2)  # the 2 June trip ended at 12:00, inside the report's day
    _trip(4, 1100, 1300)
    between = _report(3)  # the 4 June trip must not leak backwards
    incident = incident_service.create_incident(
        db_session, organization.id,
        IncidentLogCreate(
            driver_id=driver_profile.id, vehicle_id=vehicle.id, incident_type=IncidentType.damage,
            incident_time=datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc), severity=IncidentSeverity.minor, description="Mid-trip scrape",
        ),
        admin.id,
    )  # 10:00 is before the 12:00 trip end, so the earlier trip's 1100 applies

    by_id = {e.id: e for e in timeline_service.get_vehicle_timeline(db_session, organization.id, vehicle.id)}
    assert by_id[before_any_trip.id].summary["odometer"] is None
    assert by_id[same_day.id].summary["odometer"] == 1100
    assert by_id[between.id].summary["odometer"] == 1100
    assert by_id[incident.id].summary["odometer"] == 1100
