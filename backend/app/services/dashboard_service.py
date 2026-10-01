import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.driver import Driver
from app.models.enums import DriverStatus, VehicleStatus
from app.models.vehicle import Vehicle
from app.schemas.dashboard import (
    DashboardSummaryResponse,
    FuelTrendPoint,
    MaintenanceCalendarItem,
    VehicleHealthScore,
    VehicleHealthSignals,
)
from app.services import compliance_service, fuel_service, incident_service, inventory_service, maintenance_service, supplier_service

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
    """Every figure is computed by the database (SELECT COUNT(*) / SUM), never by loading rows and counting them in
    Python: with tens of thousands of rows the old len(list_...) versions dominated the page load. Each count has the
    same rows as the list function it replaced (maintenance_service.list_overdue, inventory_service.list_low_stock,
    incident_service.list_incidents for open + investigating). Read-only."""
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

    return DashboardSummaryResponse(
        total_vehicles=total_vehicles,
        active_drivers=active_drivers,
        month_fuel_cost=fuel_service.month_total_cost(db, org_id),
        overdue_maintenance_count=maintenance_service.count_overdue(db, org_id),
        low_stock_parts_count=inventory_service.count_low_stock(db, org_id),
        open_incidents_count=incident_service.count_unresolved(db, org_id),
        active_suppliers_count=supplier_service.count_active_suppliers(db, org_id),
    )


def get_fuel_trends(db: Session, org_id: uuid.UUID, months: int = 12, vehicle_id: uuid.UUID | None = None) -> list[FuelTrendPoint]:
    rows = fuel_service.get_fuel_cost_trend(db, org_id, months=months, vehicle_id=vehicle_id)
    return [FuelTrendPoint(month=month, total_cost=total_cost, avg_cost_per_km=avg) for month, total_cost, avg in rows]


def get_maintenance_calendar_page(
    db: Session, org_id: uuid.UUID, window_days: int = 30, *, limit: int | None = None, offset: int = 0, search: str | None = None,
    vehicle_id: uuid.UUID | None = None,
) -> tuple[list[MaintenanceCalendarItem], int]:
    """
    Overdue items (unfiltered by window -- an item never drops off for being
    "too overdue") plus items due within window_days that are not already
    overdue, so the same (vehicle, service_type) never appears twice. Uses the
    date window, not list_upcoming's km window: that would miss vehicles with no
    service_interval_km configured and include ones whose km-distance is close
    but whose calendar date isn't (see maintenance_service.list_upcoming_by_date).

    Ordered latest due date first, and paged IN SQL: returns
    (the requested page, the total across all pages). limit=None returns everything.
    """
    rows, total = maintenance_service.calendar_page(db, org_id, window_days=window_days, limit=limit, offset=offset, search=search, vehicle_id=vehicle_id)
    return [
        MaintenanceCalendarItem(
            vehicle_id=vehicle_id,
            plate_number=plate,
            vehicle_name=f"{make} {model}",
            driver_name=driver_name,
            last_service_date=last_date,
            service_type=service_type,
            due_date=due_date,
            due_km=due_km,
            status=status,
        )
        for vehicle_id, plate, make, model, driver_name, last_date, service_type, due_date, due_km, status in rows
    ], total


def get_maintenance_calendar(db: Session, org_id: uuid.UUID, window_days: int = 30) -> list[MaintenanceCalendarItem]:
    """The whole calendar (no paging): the form the AI agents' tools use."""
    return get_maintenance_calendar_page(db, org_id, window_days)[0]


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


def fleet_makes(db: Session, org_id: uuid.UUID) -> list[str]:
    """Distinct makes of the organization's vehicles, for the filter dropdown."""
    return list(
        db.execute(
            select(Vehicle.make).where(Vehicle.organization_id == org_id, Vehicle.is_deleted.is_(False)).distinct().order_by(Vehicle.make)
        ).scalars()
    )


def get_fleet_health_page(
    db: Session,
    org_id: uuid.UUID,
    *,
    limit: int | None = None,
    offset: int = 0,
    search: str | None = None,
    health_min: float | None = None,
    health_max: float | None = None,
    make: str | None = None,
    status: VehicleStatus | None = None,
) -> tuple[list[VehicleHealthScore], int]:
    """Health score per non-retired vehicle. Every signal is computed fleet-wide in a handful of queries (compliance
    rules and latest services, incident counts, fuel cost/km periods, overdue and due-soon vehicles) rather than a few
    queries per vehicle. With `limit`, the result is sorted worst first (then by plate) and cut to that page; without
    it every vehicle is returned in query order. Returns (vehicles, total number of scored vehicles)."""
    # search / make / status are WHERE clauses on the vehicles query, so only matching vehicles are scored. The score is
    # computed (it is not a column), so health_min / health_max are applied to the scores, still before limit/offset,
    # and the total is the filtered count. Retired vehicles are left out unless status asks for them.
    stmt = select(Vehicle).where(Vehicle.organization_id == org_id, Vehicle.is_deleted.is_(False))
    stmt = stmt.where(Vehicle.status == status) if status is not None else stmt.where(Vehicle.status != VehicleStatus.retired)
    if make:
        stmt = stmt.where(Vehicle.make == make)
    if search and search.strip():
        stmt = stmt.where(maintenance_service.vehicle_search_clause(search))
    vehicles = list(db.execute(stmt).scalars())
    if not vehicles:
        return [], 0

    overdue_vehicle_ids = maintenance_service.overdue_vehicle_ids(db, org_id)
    due_soon_vehicle_ids = maintenance_service.due_soon_vehicle_ids(db, org_id)
    compliance_by_vehicle = compliance_service.compliance_statuses_by_vehicle(db, org_id, vehicles)
    incident_counts = incident_service.recent_incident_counts(db, org_id)
    fuel_periods = fuel_service.cost_per_km_periods_by_vehicle(db, org_id)

    results: list[VehicleHealthScore] = []
    for vehicle in vehicles:
        statuses = compliance_by_vehicle.get(vehicle.id) or []
        if statuses:
            compliance_signal = round(sum(_COMPLIANCE_STATUS_SCORES[status] for status in statuses) / len(statuses))
        else:
            compliance_signal = None  # no applicable rules -- excluded, not defaulted (spec EC-4)

        incidents_signal = _incident_signal(incident_counts.get(vehicle.id, 0))

        if vehicle.id in overdue_vehicle_ids:
            maintenance_signal = 10
        elif vehicle.id in due_soon_vehicle_ids:
            maintenance_signal = 60
        else:
            maintenance_signal = 100

        current_avg, prior_avg = fuel_periods.get(vehicle.id, (None, None))
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
    if health_min is not None:
        results = [r for r in results if r.health_score >= health_min]
    if health_max is not None:
        results = [r for r in results if r.health_score <= health_max]
    total = len(results)
    if limit is not None:
        results.sort(key=lambda r: (r.health_score, r.plate_number))
        results = results[offset : offset + limit]
    return results, total


def get_fleet_health(db: Session, org_id: uuid.UUID) -> list[VehicleHealthScore]:
    """Every scored vehicle (no paging), in query order: the form the AI agents' tools use."""
    return get_fleet_health_page(db, org_id)[0]
