import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.enums import (
    DriverStatus,
    IncidentSeverity,
    IncidentType,
    ServiceType,
    UserRole,
    VehicleStatus,
)
from app.models.organization import Organization
from app.schemas.fuel import FuelLogCreate
from app.schemas.accountability import IncidentLogCreate
from app.services import dashboard_service, incident_service, inventory_service, maintenance_service
from tests.conftest import make_compliance_rule, make_driver, make_maintenance_log, make_part, make_user, make_vehicle

TODAY = date(2026, 9, 18)


@pytest.fixture()
def admin(db_session: Session, organization: Organization):
    return make_user(db_session, organization, role=UserRole.admin)


# --- get_summary -----------------------------------------------------------------


def test_summary_matches_manual_counts(db_session: Session, organization: Organization, admin) -> None:
    make_vehicle(db_session, organization, status=VehicleStatus.active)
    make_vehicle(db_session, organization, status=VehicleStatus.maintenance)
    make_vehicle(db_session, organization, status=VehicleStatus.retired)  # excluded

    make_driver(db_session, organization, status=DriverStatus.active)
    make_driver(db_session, organization, status=DriverStatus.active)
    make_driver(db_session, organization, status=DriverStatus.suspended)  # excluded

    fuel_vehicle = make_vehicle(db_session, organization, current_odometer=0)
    from app.services import fuel_service

    fuel_service.create_fuel_log(
        db_session, organization.id,
        FuelLogCreate(vehicle_id=fuel_vehicle.id, date=datetime.now(timezone.utc).date(), odometer_reading=100, liters_filled=Decimal("10.00"), price_per_liter=Decimal("20.00"), total_cost=Decimal("200.00")),
        admin.id,
    )

    overdue_vehicle = make_vehicle(db_session, organization, current_odometer=20000)
    make_maintenance_log(db_session, organization, overdue_vehicle, odometer_at_service=1000, next_due_km=15000, next_due_date=date(2030, 1, 1))

    part = make_part(db_session, organization, qty_on_hand=1, reorder_threshold=5)

    incident_vehicle = make_vehicle(db_session, organization)
    incident_service.create_incident(
        db_session, organization.id,
        IncidentLogCreate(vehicle_id=incident_vehicle.id, incident_type=IncidentType.damage, date=TODAY, severity=IncidentSeverity.minor, description="Scratch"),
        admin.id,
    )

    summary = dashboard_service.get_summary(db_session, organization.id)
    # 2 from the explicit active/maintenance pair (retired excluded) + 3 more
    # default-status (active) vehicles created for the fuel/maintenance/
    # incident fixtures below -- all non-retired, all counted.
    assert summary.total_vehicles == 5
    assert summary.active_drivers == 2
    assert summary.month_fuel_cost == Decimal("200.00")
    assert summary.overdue_maintenance_count == 1
    assert summary.low_stock_parts_count == 1
    assert summary.open_incidents_count == 1
    assert part.id  # keep reference alive for readability


def test_summary_zero_vehicles_returns_zero_counts(db_session: Session, organization: Organization) -> None:
    summary = dashboard_service.get_summary(db_session, organization.id)
    assert summary.total_vehicles == 0
    assert summary.active_drivers == 0
    assert summary.month_fuel_cost == 0
    assert summary.overdue_maintenance_count == 0


# --- get_fuel_trends ---------------------------------------------------------------


def test_fuel_trends_covers_requested_month_range_including_empty_months(
    db_session: Session, organization: Organization, admin
) -> None:
    from app.services import fuel_service

    vehicle = make_vehicle(db_session, organization, current_odometer=0)
    fuel_service.create_fuel_log(
        db_session, organization.id,
        FuelLogCreate(vehicle_id=vehicle.id, date=TODAY, odometer_reading=100, liters_filled=Decimal("10.00"), price_per_liter=Decimal("15.00"), total_cost=Decimal("150.00")),
        admin.id,
    )

    trends = dashboard_service.get_fuel_trends(db_session, organization.id, months=6)
    assert len(trends) == 6
    current_month_key = f"{TODAY.year:04d}-{TODAY.month:02d}"
    current_point = next(p for p in trends if p.month == current_month_key)
    assert current_point.total_cost == Decimal("150.00")

    empty_points = [p for p in trends if p.month != current_month_key]
    assert all(p.total_cost == 0 and p.avg_cost_per_km is None for p in empty_points)


# --- get_maintenance_calendar --------------------------------------------------------


def test_maintenance_calendar_includes_far_overdue_items(db_session: Session, organization: Organization) -> None:
    vehicle = make_vehicle(db_session, organization, current_odometer=100)
    make_maintenance_log(
        db_session, organization, vehicle, odometer_at_service=50, next_due_km=100000,
        next_due_date=date(2020, 1, 1),  # ~200+ days overdue relative to any "today" well past 2020
    )
    calendar = dashboard_service.get_maintenance_calendar(db_session, organization.id, window_days=30)
    assert any(item.status == "overdue" and item.vehicle_id == vehicle.id for item in calendar)


def test_maintenance_calendar_excludes_far_future_upcoming(db_session: Session, organization: Organization) -> None:
    vehicle = make_vehicle(db_session, organization, current_odometer=100)
    make_maintenance_log(
        db_session, organization, vehicle, odometer_at_service=50, next_due_km=100000,
        next_due_date=date(2030, 1, 1),  # far beyond a 30-day window
    )
    calendar = dashboard_service.get_maintenance_calendar(db_session, organization.id, window_days=30)
    assert not any(item.vehicle_id == vehicle.id for item in calendar)


def test_maintenance_calendar_no_duplicate_when_overdue_by_km_but_due_date_within_window(
    db_session: Session, organization: Organization
) -> None:
    """A vehicle overdue by km but whose next_due_date still falls inside the
    day window must appear once (as overdue), not twice."""
    from datetime import datetime, timezone

    near_future = (datetime.now(timezone.utc).date() + timedelta(days=5))
    vehicle = make_vehicle(db_session, organization, current_odometer=99999)
    make_maintenance_log(
        db_session, organization, vehicle, odometer_at_service=0, next_due_km=100,  # already overdue by km
        next_due_date=near_future,  # but "upcoming" by date
    )
    calendar = dashboard_service.get_maintenance_calendar(db_session, organization.id, window_days=30)
    matches = [item for item in calendar if item.vehicle_id == vehicle.id]
    assert len(matches) == 1
    assert matches[0].status == "overdue"


def test_maintenance_calendar_overdue_with_no_due_date_still_included(db_session: Session, organization: Organization) -> None:
    """An item overdue purely by km (no service_interval_months configured)
    has next_due_date=None but must not be dropped from the calendar."""
    vehicle = make_vehicle(db_session, organization, current_odometer=5000)
    make_maintenance_log(db_session, organization, vehicle, odometer_at_service=0, next_due_km=1000, next_due_date=None)
    calendar = dashboard_service.get_maintenance_calendar(db_session, organization.id)
    match = next(item for item in calendar if item.vehicle_id == vehicle.id)
    assert match.status == "overdue"
    assert match.due_date is None


# --- get_fleet_health ---------------------------------------------------------------


def test_fleet_health_excludes_missing_compliance_signal_from_average(
    db_session: Session, organization: Organization
) -> None:
    no_rules_vehicle = make_vehicle(db_session, organization, make="Isuzu", model="NPR", current_odometer=100)
    with_rules_vehicle = make_vehicle(db_session, organization, make="Toyota", model="Hilux", current_odometer=100)
    make_compliance_rule(db_session, organization, vehicle_make="Toyota", vehicle_model="Hilux", interval_km=10000, interval_months=120)
    make_maintenance_log(db_session, organization, with_rules_vehicle, service_type=ServiceType.oil_change, odometer_at_service=50, date=date(2026, 9, 1))

    results = dashboard_service.get_fleet_health(db_session, organization.id)
    no_rules_result = next(r for r in results if r.vehicle_id == no_rules_vehicle.id)
    with_rules_result = next(r for r in results if r.vehicle_id == with_rules_vehicle.id)

    assert no_rules_result.signals.compliance is None
    assert with_rules_result.signals.compliance == 100  # compliant


def test_fleet_health_incident_signal_buckets(db_session: Session, organization: Organization, admin) -> None:
    assert dashboard_service._incident_signal(0) == 100
    assert dashboard_service._incident_signal(1) == 70
    assert dashboard_service._incident_signal(2) == 40
    assert dashboard_service._incident_signal(3) == 10
    assert dashboard_service._incident_signal(50) == 10


def test_fleet_health_fuel_efficiency_signal_boundaries() -> None:
    assert dashboard_service._fuel_efficiency_signal(None, Decimal("10")) is None
    assert dashboard_service._fuel_efficiency_signal(Decimal("10"), None) is None
    assert dashboard_service._fuel_efficiency_signal(Decimal("9"), Decimal("10")) == 100  # improved
    assert dashboard_service._fuel_efficiency_signal(Decimal("10"), Decimal("10")) == 100  # flat
    assert dashboard_service._fuel_efficiency_signal(Decimal("11"), Decimal("10")) == 60  # +10%, moderate
    assert dashboard_service._fuel_efficiency_signal(Decimal("12.01"), Decimal("10")) == 20  # >20%, sharp


def test_fleet_health_weighted_score_renormalizes_available_signals() -> None:
    all_present = dashboard_service._weighted_health_score(
        {"compliance": 100, "incidents": 100, "maintenance_currency": 100, "fuel_efficiency": 100}
    )
    assert all_present == 100

    one_missing = dashboard_service._weighted_health_score(
        {"compliance": None, "incidents": 100, "maintenance_currency": 100, "fuel_efficiency": 100}
    )
    assert one_missing == 100  # renormalized -- not deflated by the missing 30% weight


def test_fleet_health_empty_fleet_returns_empty_list(db_session: Session, organization: Organization) -> None:
    assert dashboard_service.get_fleet_health(db_session, organization.id) == []


# --- read-only guarantee ------------------------------------------------------------


def test_dashboard_service_never_writes() -> None:
    """Static check: no function in dashboard_service.py calls db.add/db.commit/db.delete/db.execute of a write statement."""
    import inspect

    source = inspect.getsource(dashboard_service)
    assert "db.add(" not in source
    assert "db.commit(" not in source
    assert "db.delete(" not in source
    assert ".flush()" not in source


# --- org scoping -----------------------------------------------------------------


def test_org_scoping(db_session: Session, organization: Organization, admin) -> None:
    make_vehicle(db_session, organization)

    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()

    summary = dashboard_service.get_summary(db_session, other_org.id)
    assert summary.total_vehicles == 0
    assert dashboard_service.get_fleet_health(db_session, other_org.id) == []
    assert dashboard_service.get_maintenance_calendar(db_session, other_org.id) == []


# --- fuel cost-per-km periods behind the fuel_efficiency signal ------------------


def _fuel_log(db_session: Session, organization: Organization, vehicle, day: date, cost_per_km: str) -> None:
    from app.models.fuel import FuelLog

    db_session.add(
        FuelLog(
            id=uuid.uuid4(), organization_id=organization.id, vehicle_id=vehicle.id, date=day, odometer_reading=1000,
            liters_filled=Decimal("40"), price_per_liter=Decimal("280"), total_cost=Decimal("11200"),
            cost_per_km=Decimal(cost_per_km),
        )
    )
    db_session.commit()


def test_cost_per_km_current_period_includes_today_and_later_slip_dates(db_session: Session, organization: Organization) -> None:
    from app.services import fuel_service

    vehicle = make_vehicle(db_session, organization)
    _fuel_log(db_session, organization, vehicle, TODAY, "30.00")
    _fuel_log(db_session, organization, vehicle, TODAY + timedelta(days=2), "28.00")

    current, previous = fuel_service.get_vehicle_cost_per_km_periods(db_session, organization.id, vehicle.id, as_of=TODAY)
    assert current == Decimal("29.0000")
    assert previous is None


def test_fleet_health_exposes_cost_per_km_even_without_a_previous_period(
    db_session: Session, organization: Organization, monkeypatch
) -> None:
    from app.services import fuel_service

    vehicle = make_vehicle(db_session, organization)
    real = fuel_service.get_vehicle_cost_per_km_periods
    monkeypatch.setattr(
        fuel_service, "get_vehicle_cost_per_km_periods", lambda db, org_id, vehicle_id: real(db, org_id, vehicle_id, as_of=TODAY)
    )
    _fuel_log(db_session, organization, vehicle, TODAY - timedelta(days=10), "31.50")

    entry = next(r for r in dashboard_service.get_fleet_health(db_session, organization.id) if r.vehicle_id == vehicle.id)
    assert entry.signals.fuel_efficiency is None  # nothing to compare against: still excluded from the score
    assert entry.current_cost_per_km == Decimal("31.5000")
    assert entry.previous_cost_per_km is None

    _fuel_log(db_session, organization, vehicle, TODAY - timedelta(days=120), "35.00")
    entry = next(r for r in dashboard_service.get_fleet_health(db_session, organization.id) if r.vehicle_id == vehicle.id)
    assert entry.previous_cost_per_km == Decimal("35.0000")
    assert entry.signals.fuel_efficiency == 100  # cheaper per km than before
