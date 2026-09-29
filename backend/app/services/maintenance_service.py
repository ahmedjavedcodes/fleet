import calendar
import uuid
from datetime import date as date_type
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.driver import Driver
from app.models.enums import ServiceType
from app.models.maintenance import MaintenanceLog, MaintenanceLogService, MechanicReport
from app.models.vehicle import Vehicle
from app.schemas.maintenance import (
    MaintenanceLogCreate,
    MaintenanceLogUpdate,
    MechanicReportCreate,
    OverdueMaintenanceItem,
    UpcomingMaintenanceItem,
)
from app.services import inventory_service

_DUPLICATE_REPORT_ERROR = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="This maintenance log already has a mechanic report"
)


def _add_months(d: date_type, months: int) -> date_type:
    """Calendar-accurate month addition (clamps to the last valid day of the
    target month, e.g. Jan 31 + 1 month -> Feb 28/29). Reused by
    compliance_service for the equivalent rule-interval-to-date conversion."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date_type(year, month, day)


def _get_vehicle_or_404(db: Session, org_id: uuid.UUID, vehicle_id: uuid.UUID) -> Vehicle:
    vehicle = db.execute(
        select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.organization_id == org_id, Vehicle.is_deleted.is_(False))
    ).scalar_one_or_none()
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    return vehicle


def _validate_driver(db: Session, org_id: uuid.UUID, driver_id: uuid.UUID | None) -> None:
    if driver_id is None:
        return
    driver = db.execute(
        select(Driver).where(Driver.id == driver_id, Driver.organization_id == org_id, Driver.is_deleted.is_(False))
    ).scalar_one_or_none()
    if driver is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found")


def _build_services(service_types) -> list[MaintenanceLogService]:
    return [MaintenanceLogService(id=uuid.uuid4(), service_type=t, position=i) for i, t in enumerate(service_types)]


def _compute_next_due(vehicle: Vehicle, odometer_at_service: int, service_date: date_type) -> tuple[int | None, date_type | None]:
    next_due_km = odometer_at_service + vehicle.service_interval_km if vehicle.service_interval_km is not None else None
    next_due_date = _add_months(service_date, vehicle.service_interval_months) if vehicle.service_interval_months is not None else None
    return next_due_km, next_due_date


def create_maintenance_log(db: Session, org_id: uuid.UUID, data: MaintenanceLogCreate, created_by: uuid.UUID) -> MaintenanceLog:
    """Computes and freezes next_due_km/next_due_date at creation. Does NOT
    update Vehicle.current_odometer -- odometer currency comes from fuel/trip
    logging (Specs 01/04), not maintenance logging."""
    vehicle = _get_vehicle_or_404(db, org_id, data.vehicle_id)
    _validate_driver(db, org_id, data.driver_id)
    next_due_km, next_due_date = _compute_next_due(vehicle, data.odometer_at_service, data.date)

    log = MaintenanceLog(
        id=uuid.uuid4(),
        organization_id=org_id,
        created_by=created_by,
        vehicle_id=data.vehicle_id,
        date=data.date,
        odometer_at_service=data.odometer_at_service,
        service_type=data.service_types[0],
        service_scale=data.service_scale,
        driver_id=data.driver_id,
        description=data.description,
        cost=data.cost,
        mechanic_name=data.mechanic_name,
        next_due_km=next_due_km,
        next_due_date=next_due_date,
        services=_build_services(data.service_types),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def get_maintenance_log(
    db: Session, org_id: uuid.UUID, log_id: uuid.UUID, *, created_by: uuid.UUID | None = None
) -> MaintenanceLog:
    """Eager-loads mechanic_report. created_by restricts to logs that user recorded
    (a mechanic's "own jobs"); anyone else's log is a 404, not a 403, so its
    existence isn't disclosed."""
    stmt = (
        select(MaintenanceLog)
        .where(MaintenanceLog.id == log_id, MaintenanceLog.organization_id == org_id, MaintenanceLog.is_deleted.is_(False))
        .options(selectinload(MaintenanceLog.mechanic_report))
    )
    if created_by is not None:
        stmt = stmt.where(MaintenanceLog.created_by == created_by)
    log = db.execute(stmt).scalar_one_or_none()
    if log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance log not found")
    return log


def list_maintenance_logs(
    db: Session,
    org_id: uuid.UUID,
    *,
    vehicle_id: uuid.UUID | None = None,
    service_type=None,
    date_from: date_type | None = None,
    date_to: date_type | None = None,
    created_by: uuid.UUID | None = None,
) -> list[MaintenanceLog]:
    stmt = select(MaintenanceLog).where(MaintenanceLog.organization_id == org_id, MaintenanceLog.is_deleted.is_(False))
    if created_by is not None:
        stmt = stmt.where(MaintenanceLog.created_by == created_by)
    if vehicle_id is not None:
        stmt = stmt.where(MaintenanceLog.vehicle_id == vehicle_id)
    if service_type is not None:
        # A visit can include several services -- match on any of them.
        stmt = stmt.where(
            MaintenanceLog.id.in_(
                select(MaintenanceLogService.maintenance_log_id).where(MaintenanceLogService.service_type == service_type)
            )
        )
    if date_from is not None:
        stmt = stmt.where(MaintenanceLog.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(MaintenanceLog.date <= date_to)
    stmt = stmt.order_by(MaintenanceLog.date.desc())
    return list(db.execute(stmt).scalars())


def update_maintenance_log(
    db: Session, org_id: uuid.UUID, log_id: uuid.UUID, data: MaintenanceLogUpdate, updated_by: uuid.UUID
) -> MaintenanceLog:
    """Recomputes next_due_km/next_due_date only if odometer_at_service or date
    changed, using the vehicle's *current* interval settings -- unlike FuelLog,
    there is no freeze-on-edit rule here (see backendPlan.md)."""
    log = get_maintenance_log(db, org_id, log_id)
    updates = data.model_dump(exclude_unset=True)
    recompute = "odometer_at_service" in updates or "date" in updates

    if "driver_id" in updates:
        _validate_driver(db, org_id, updates["driver_id"])
    service_types = updates.pop("service_types", None)
    if service_types is not None:
        log.service_type = service_types[0]
        log.services = _build_services(service_types)

    for field, value in updates.items():
        setattr(log, field, value)

    if recompute:
        vehicle = _get_vehicle_or_404(db, org_id, log.vehicle_id)
        log.next_due_km, log.next_due_date = _compute_next_due(vehicle, log.odometer_at_service, log.date)

    log.updated_by = updated_by
    db.commit()
    db.refresh(log)
    return log


def create_mechanic_report(
    db: Session, org_id: uuid.UUID, log_id: uuid.UUID, data: MechanicReportCreate, created_by: uuid.UUID
) -> tuple[MechanicReport, list[dict]]:
    """
    Single transaction:
      1. Fetch the MaintenanceLog (org-scoped) -- 404 if missing.
      2. Reject if a MechanicReport already exists for this log (1:1, create-only).
      3. Insert the report with parts_used stored as-is -- no parsing, no NLP.
      4. Decrement inventory stock for parts_used, inside this same transaction.
      5. Commit. Roll back both the report insert and the stock decrement together
         on any failure.
    Returns (report, alerts) so the router can include low_stock_alerts in the response.
    """
    log = get_maintenance_log(db, org_id, log_id)

    existing = db.execute(
        select(MechanicReport).where(MechanicReport.maintenance_log_id == log.id, MechanicReport.is_deleted.is_(False))
    ).scalar_one_or_none()
    if existing is not None:
        raise _DUPLICATE_REPORT_ERROR

    parts_used = [p.model_dump(mode="json") for p in data.parts_used]

    report = MechanicReport(
        id=uuid.uuid4(),
        organization_id=org_id,
        created_by=created_by,
        maintenance_log_id=log.id,
        diagnostic_notes=data.diagnostic_notes,
        findings=data.findings,
        actions_taken=data.actions_taken,
        parts_used=parts_used,
        recommendations=data.recommendations,
    )
    db.add(report)

    alerts = inventory_service.decrement_stock_for_parts_used(db, org_id, parts_used)

    db.commit()
    db.refresh(report)
    return report, alerts


def _latest_logs_joined_with_vehicle(
    db: Session, org_id: uuid.UUID
) -> list[tuple[MaintenanceLog, Vehicle, ServiceType]]:
    """The latest MaintenanceLog per (vehicle_id, service_type), joined to its
    Vehicle -- shared by list_upcoming and list_overdue so an old, superseded
    log never causes either to flag a vehicle incorrectly. A log covering
    several services (MaintenanceLogService rows) counts as the latest for each
    of them, so the returned service_type comes from the service row, not from
    the log's primary service_type. Known limitation: if two logs for the same
    (vehicle, service_type) share the exact same date, both are returned rather
    than picking one -- an acceptable rarity at this scale, not worth a
    window-function query."""
    latest = (
        select(
            MaintenanceLog.vehicle_id,
            MaintenanceLogService.service_type,
            func.max(MaintenanceLog.date).label("max_date"),
        )
        .join(MaintenanceLogService, MaintenanceLogService.maintenance_log_id == MaintenanceLog.id)
        .where(MaintenanceLog.organization_id == org_id, MaintenanceLog.is_deleted.is_(False))
        .group_by(MaintenanceLog.vehicle_id, MaintenanceLogService.service_type)
        .subquery()
    )
    stmt = (
        select(MaintenanceLog, Vehicle, MaintenanceLogService.service_type)
        .join(Vehicle, Vehicle.id == MaintenanceLog.vehicle_id)
        .join(MaintenanceLogService, MaintenanceLogService.maintenance_log_id == MaintenanceLog.id)
        .join(
            latest,
            (MaintenanceLog.vehicle_id == latest.c.vehicle_id)
            & (MaintenanceLogService.service_type == latest.c.service_type)
            & (MaintenanceLog.date == latest.c.max_date),
        )
        .where(MaintenanceLog.organization_id == org_id, MaintenanceLog.is_deleted.is_(False), Vehicle.is_deleted.is_(False))
    )
    return list(db.execute(stmt).all())


def _item_fields(log: MaintenanceLog, vehicle: Vehicle, service_type: ServiceType) -> dict:
    """Fields shared by UpcomingMaintenanceItem/OverdueMaintenanceItem."""
    return {
        "vehicle_id": vehicle.id,
        "plate_number": vehicle.plate_number,
        "vehicle_name": f"{vehicle.make} {vehicle.model}",
        "service_type": service_type,
        "driver_name": log.driver_name,
        "last_service_date": log.date,
        "next_due_km": log.next_due_km,
        "next_due_date": log.next_due_date,
        "current_odometer": vehicle.current_odometer,
    }


def list_upcoming(db: Session, org_id: uuid.UUID, window_km: int = 1000) -> list[UpcomingMaintenanceItem]:
    """Vehicles where 0 <= (next_due_km - current_odometer) < window_km, using
    only the latest log per (vehicle, service_type). Read-time comparison, no
    stored flag."""
    items: list[UpcomingMaintenanceItem] = []
    for log, vehicle, service_type in _latest_logs_joined_with_vehicle(db, org_id):
        if log.next_due_km is None:
            continue
        km_remaining = log.next_due_km - vehicle.current_odometer
        if 0 <= km_remaining < window_km:
            items.append(
                UpcomingMaintenanceItem(
                    **_item_fields(log, vehicle, service_type),
                    service_scale=log.service_scale,
                    km_remaining=km_remaining,
                )
            )
    return items


def list_upcoming_by_date(db: Session, org_id: uuid.UUID, window_days: int = 30) -> list[UpcomingMaintenanceItem]:
    """
    Vehicles where 0 <= (next_due_date - today).days < window_days, using
    only the latest log per (vehicle, service_type).

    This is a DIFFERENT dimension than list_upcoming's km-based window: a
    vehicle whose interval is defined purely in months (no
    service_interval_km configured) has next_due_km=None and is silently
    skipped by list_upcoming, which would make it invisible on a genuinely
    date-based calendar. Built for Spec 05's maintenance calendar, which
    needs "due within N days", not "due within N km" -- reuses the same
    latest-log-per-group join as list_upcoming/list_overdue rather than
    duplicating it, but applies a distinct (date, not km) filter condition,
    since the two aren't the same query with different constants.
    """
    today = datetime.now(timezone.utc).date()
    items: list[UpcomingMaintenanceItem] = []
    for log, vehicle, service_type in _latest_logs_joined_with_vehicle(db, org_id):
        if log.next_due_date is None:
            continue
        days_remaining = (log.next_due_date - today).days
        if 0 <= days_remaining < window_days:
            km_remaining = log.next_due_km - vehicle.current_odometer if log.next_due_km is not None else None
            items.append(
                UpcomingMaintenanceItem(
                    **_item_fields(log, vehicle, service_type),
                    service_scale=log.service_scale,
                    km_remaining=km_remaining,
                )
            )
    return items


def list_overdue(db: Session, org_id: uuid.UUID) -> list[OverdueMaintenanceItem]:
    """Vehicles where current_odometer > next_due_km OR today > next_due_date,
    using only the latest log per (vehicle, service_type)."""
    today = datetime.now(timezone.utc).date()
    items: list[OverdueMaintenanceItem] = []
    for log, vehicle, service_type in _latest_logs_joined_with_vehicle(db, org_id):
        overdue_by_km = log.next_due_km is not None and vehicle.current_odometer > log.next_due_km
        overdue_by_date = log.next_due_date is not None and today > log.next_due_date
        if overdue_by_km or overdue_by_date:
            km_remaining = log.next_due_km - vehicle.current_odometer if log.next_due_km is not None else None
            items.append(
                OverdueMaintenanceItem(
                    **_item_fields(log, vehicle, service_type),
                    service_scale=log.service_scale,
                    km_remaining=km_remaining,
                )
            )
    return items
