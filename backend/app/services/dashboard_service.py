import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.driver import Driver
from app.models.enums import DriverStatus, IncidentResolutionStatus, VehicleStatus
from app.models.vehicle import Vehicle
from app.schemas.dashboard import (
    DashboardSummaryResponse,
    FuelTrendPoint,
    MaintenanceCalendarItem,
    VehicleHealthScore,
    VehicleHealthSignals,
)
from app.services import compliance_service, fuel_service, incident_service, inventory_service, maintenance_service

# --- Fleet-health business constants -----------------------------------------
#
# Weights and incident buckets below are the plan's own suggested example
# values (plans/05-strategic-insights.md §3, specs/05 §3.4), adopted as the
# initial default. The plan explicitly flags the WEIGHTS as "a business
# decision, confirm ... before treating it as final" -- these have NOT been
# confirmed with a product owner/fleet manager and should be revisited before
# this score is used for anything consequential.

HEALTH_WEIGHTS: dict[str, Decimal] = {
    "compliance": Decimal("0.30"),
    "incidents": Decimal("0.25"),
    "maintenance_currency": Decimal("0.25"),
    "fuel_efficiency": Decimal("0.20"),
}

_COMPLIANCE_STATUS_SCORES = {"compliant": 100, "due_soon": 60, "overdue": 20, "never_performed": 0}
_INCIDENT_SIGNAL_BUCKETS = {0: 100, 1: 70, 2: 40}  # 3+ falls through to the default below
_INCIDENT_SIGNAL_DEFAULT = 10


def get_summary(db: Session, org_id: uuid.UUID) -> DashboardSummaryResponse:
    """Composes existing service functions -- does not reimplement any of
    their queries. Every value reflects the same instant; no writes."""
    total_vehicles = db.execute(
        select(func.count(Vehicle.id)).where(
            Vehicle.organization_id == org_id, Vehicle.is_deleted.is_(False), Vehicle.status != VehicleStatus.retired
        )
    ).scalar_one()
    active_drivers = db.execute(
        select(func.count(Driver.id)).where(
            Driver.organization_id == org_id, Driver.is_deleted.is_(False), Driver.status == DriverStatus.active
        )
    ).scalar_one()

    month_fuel_cost = fuel_service.get_monthly_summary(db, org_id, month=None).total_cost
    overdue_maintenance_count = len(maintenance_service.list_overdue(db, org_id))
    low_stock_parts_count = len(inventory_service.list_low_stock(db, org_id))
    open_incidents_count = len(
        incident_service.list_incidents(db, org_id, resolution_status=IncidentResolutionStatus.open)
    ) + len(incident_service.list_incidents(db, org_id, resolution_status=IncidentResolutionStatus.investigating))

    return DashboardSummaryResponse(
        total_vehicles=total_vehicles,
        active_drivers=active_drivers,
        month_fuel_cost=month_fuel_cost,
        overdue_maintenance_count=overdue_maintenance_count,
        low_stock_parts_count=low_stock_parts_count,
        open_incidents_count=open_incidents_count,
    )


def get_fuel_trends(db: Session, org_id: uuid.UUID, months: int = 12) -> list[FuelTrendPoint]:
    rows = fuel_service.get_fuel_cost_trend(db, org_id, months=months)
    return [FuelTrendPoint(month=month, total_cost=total_cost, avg_cost_per_km=avg) for month, total_cost, avg in rows]


def get_maintenance_calendar(db: Session, org_id: uuid.UUID, window_days: int = 30) -> list[MaintenanceCalendarItem]:
    """
    Merges overdue items (unfiltered by window -- an item never drops off for
    being "too overdue") with items due within window_days. Uses
    list_upcoming_by_date, not list_upcoming: the latter's window is km-based
    and would both miss vehicles with no service_interval_km configured and
    include vehicles whose km-distance is close but whose calendar date isn't
    -- the wrong dimension for a "next N days" view (see maintenance_service.
    list_upcoming_by_date's docstring for the full reasoning).
    """
    overdue = maintenance_service.list_overdue(db, org_id)
    upcoming = maintenance_service.list_upcoming_by_date(db, org_id, window_days=window_days)

    # An item overdue by km can still have a next_due_date inside the window
    # (e.g. driven far this month), which would otherwise also satisfy
    # list_upcoming_by_date -- exclude anything already counted as overdue so
    # the same (vehicle, service_type) never appears on the calendar twice.
    overdue_keys = {(o.vehicle_id, o.service_type) for o in overdue}
    upcoming = [u for u in upcoming if (u.vehicle_id, u.service_type) not in overdue_keys]

    items = [
        MaintenanceCalendarItem(
            vehicle_id=o.vehicle_id,
            plate_number=o.plate_number,
            vehicle_name=o.vehicle_name,
            driver_name=o.driver_name,
            last_service_date=o.last_service_date,
            service_type=o.service_type,
            due_date=o.next_due_date,
            due_km=o.next_due_km,
            status="overdue",
        )
        for o in overdue
    ]
    items += [
        MaintenanceCalendarItem(
            vehicle_id=u.vehicle_id,
            plate_number=u.plate_number,
            vehicle_name=u.vehicle_name,
            driver_name=u.driver_name,
            last_service_date=u.last_service_date,
            service_type=u.service_type,
            due_date=u.next_due_date,
            due_km=u.next_due_km,
            status="upcoming",
        )
        for u in upcoming
    ]
    return items


def _incident_signal(count: int) -> int:
    return _INCIDENT_SIGNAL_BUCKETS.get(count, _INCIDENT_SIGNAL_DEFAULT)


def _fuel_efficiency_signal(current_avg: Decimal | None, prior_avg: Decimal | None) -> int | None:
    """None (excluded) when either period has no data -- never defaulted to a
    penalty or a perfect score (spec EC-5)."""
    if current_avg is None or prior_avg is None or prior_avg == 0:
        return None
    deviation = (current_avg - prior_avg) / prior_avg
    if deviation <= 0:
        return 100
    if deviation <= fuel_service.ANOMALY_THRESHOLD:
        return 60
    return 20


def _weighted_health_score(signals: dict[str, int | None]) -> int:
    """Weighted average of whichever signals are available, with weights
    renormalized among the available signals only -- a vehicle missing one
    signal is scored purely on the others, never penalized for the gap
    (spec constraint #5: 'missing signals are excluded, not defaulted')."""
    total_weight = Decimal("0")
    weighted_sum = Decimal("0")
    for key, value in signals.items():
        if value is None:
            continue
        weight = HEALTH_WEIGHTS[key]
        total_weight += weight
        weighted_sum += weight * value
    if total_weight == 0:
        return 0
    return int((weighted_sum / total_weight).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_fleet_health(db: Session, org_id: uuid.UUID) -> list[VehicleHealthScore]:
    vehicles = list(
        db.execute(
            select(Vehicle).where(
                Vehicle.organization_id == org_id, Vehicle.is_deleted.is_(False), Vehicle.status != VehicleStatus.retired
            )
        ).scalars()
    )
    if not vehicles:
        return []

    # Computed once for the whole fleet, not once per vehicle -- still exact
    # reuse of the existing service functions, just called at their natural
    # (org-wide) granularity instead of N times.
    overdue_vehicle_ids = {o.vehicle_id for o in maintenance_service.list_overdue(db, org_id)}
    due_soon_vehicle_ids = {u.vehicle_id for u in maintenance_service.list_upcoming(db, org_id)}

    results: list[VehicleHealthScore] = []
    for vehicle in vehicles:
        compliance_result = compliance_service.get_vehicle_compliance(db, org_id, vehicle.id)
        if compliance_result.items:
            compliance_signal = round(
                sum(_COMPLIANCE_STATUS_SCORES[item.status] for item in compliance_result.items)
                / len(compliance_result.items)
            )
        else:
            compliance_signal = None  # no applicable rules -- excluded, not defaulted (spec EC-4)

        incident_count = incident_service.count_recent_incidents_for_vehicle(db, org_id, vehicle.id)
        incidents_signal = _incident_signal(incident_count)

        if vehicle.id in overdue_vehicle_ids:
            maintenance_signal = 10
        elif vehicle.id in due_soon_vehicle_ids:
            maintenance_signal = 60
        else:
            maintenance_signal = 100

        current_avg, prior_avg = fuel_service.get_vehicle_cost_per_km_periods(db, org_id, vehicle.id)
        fuel_signal = _fuel_efficiency_signal(current_avg, prior_avg)

        signals = {
            "compliance": compliance_signal,
            "incidents": incidents_signal,
            "maintenance_currency": maintenance_signal,
            "fuel_efficiency": fuel_signal,
        }

        results.append(
            VehicleHealthScore(
                vehicle_id=vehicle.id,
                plate_number=vehicle.plate_number,
                health_score=_weighted_health_score(signals),
                signals=VehicleHealthSignals(**signals),
                current_cost_per_km=current_avg,
                previous_cost_per_km=prior_avg,
            )
        )
    return results
