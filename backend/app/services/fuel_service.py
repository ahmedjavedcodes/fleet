import calendar
import uuid
from datetime import date as date_type
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import Numeric, cast, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.driver import Driver
from app.models.enums import FuelReceiptUploadStatus
from app.models.fuel import FuelLog, FuelReceipt
from app.models.vehicle import Vehicle
from app.schemas.fuel import FuelLogCreate, FuelLogUpdate, FuelSummaryResponse, VehicleFuelSummary

# A rolling average built from fewer than this many prior data points isn't a
# meaningful trend -- never flag an anomaly against it (spec EC-3/EC-7).
MIN_ROLLING_HISTORY = 3
ROLLING_WINDOW_MONTHS = 3
ANOMALY_THRESHOLD = Decimal("0.20")

_ALLOWED_RECEIPT_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
_DUPLICATE_RECEIPT_ERROR = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="This fuel log already has a receipt"
)


def _months_before(d: date_type, months: int) -> date_type:
    month = d.month - months
    year = d.year
    while month <= 0:
        month += 12
        year -= 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date_type(year, month, day)


def _get_vehicle_or_404(db: Session, org_id: uuid.UUID, vehicle_id: uuid.UUID) -> Vehicle:
    vehicle = db.execute(
        select(Vehicle).where(
            Vehicle.id == vehicle_id, Vehicle.organization_id == org_id, Vehicle.is_deleted.is_(False)
        )
    ).scalar_one_or_none()
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    return vehicle


def _get_previous_log(
    db: Session,
    org_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    before_date: date_type,
    before_odometer: int,
    exclude_id: uuid.UUID | None = None,
) -> FuelLog | None:
    """The vehicle's most recent prior log, ordered by date then odometer_reading
    (both descending) so out-of-order backfilled entries still find the correct
    chronological neighbor, not just the last-inserted row."""
    stmt = select(FuelLog).where(
        FuelLog.organization_id == org_id,
        FuelLog.vehicle_id == vehicle_id,
        FuelLog.is_deleted.is_(False),
        (FuelLog.date < before_date)
        | ((FuelLog.date == before_date) & (FuelLog.odometer_reading < before_odometer)),
    )
    if exclude_id is not None:
        stmt = stmt.where(FuelLog.id != exclude_id)
    stmt = stmt.order_by(FuelLog.date.desc(), FuelLog.odometer_reading.desc()).limit(1)
    return db.execute(stmt).scalar_one_or_none()


def _compute_rolling_average(
    db: Session,
    org_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    as_of_date: date_type,
    exclude_id: uuid.UUID | None,
) -> tuple[Decimal | None, int]:
    """Average cost_per_km over non-null readings in the trailing
    ROLLING_WINDOW_MONTHS, strictly before as_of_date. Returns (average, count)."""
    window_start = _months_before(as_of_date, ROLLING_WINDOW_MONTHS)
    stmt = select(FuelLog.cost_per_km).where(
        FuelLog.organization_id == org_id,
        FuelLog.vehicle_id == vehicle_id,
        FuelLog.is_deleted.is_(False),
        FuelLog.cost_per_km.is_not(None),
        FuelLog.date >= window_start,
        FuelLog.date < as_of_date,
    )
    if exclude_id is not None:
        stmt = stmt.where(FuelLog.id != exclude_id)
    values = [v for (v,) in db.execute(stmt).all()]
    if not values:
        return None, 0
    return sum(values) / len(values), len(values)


def _compute_cost_per_km_and_anomaly(
    db: Session,
    org_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    log_date: date_type,
    odometer_reading: int,
    total_cost: Decimal,
    exclude_id: uuid.UUID | None,
) -> tuple[Decimal | None, bool]:
    prior = _get_previous_log(db, org_id, vehicle_id, log_date, odometer_reading, exclude_id=exclude_id)
    if prior is None:
        return None, False

    delta = odometer_reading - prior.odometer_reading
    if delta <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="odometer_reading must be greater than the vehicle's previous fuel log reading",
        )
    cost_per_km = total_cost / Decimal(delta)

    avg, count = _compute_rolling_average(db, org_id, vehicle_id, log_date, exclude_id)
    is_anomalous = False
    if avg is not None and count >= MIN_ROLLING_HISTORY and avg != 0:
        deviation = abs(cost_per_km - avg) / avg
        is_anomalous = deviation > ANOMALY_THRESHOLD
    return cost_per_km, is_anomalous


def create_fuel_log(
    db: Session,
    org_id: uuid.UUID,
    data: FuelLogCreate,
    created_by: uuid.UUID,
    driver_id_override: uuid.UUID | None = None,
) -> FuelLog:
    """
    Single transaction: compute cost_per_km + is_anomalous, insert the log, and
    update Vehicle.current_odometer as a side effect -- all or nothing.

    driver_id_override forces driver_id regardless of the request body -- used
    when the caller is a 'driver'-role user, who can only ever log fuel for
    themself (enforced in the router, not here).
    """
    vehicle = _get_vehicle_or_404(db, org_id, data.vehicle_id)

    cost_per_km, is_anomalous = _compute_cost_per_km_and_anomaly(
        db, org_id, data.vehicle_id, data.date, data.odometer_reading, data.total_cost, exclude_id=None
    )

    fuel_log = FuelLog(
        id=uuid.uuid4(),
        organization_id=org_id,
        created_by=created_by,
        vehicle_id=data.vehicle_id,
        driver_id=driver_id_override if driver_id_override is not None else data.driver_id,
        date=data.date,
        odometer_reading=data.odometer_reading,
        liters_filled=data.liters_filled,
        price_per_liter=data.price_per_liter,
        total_cost=data.total_cost,
        cost_per_km=cost_per_km,
        is_anomalous=is_anomalous,
        notes=data.notes,
        po_number=data.po_number,
        payment_method=data.payment_method,
        card_used=data.card_used,
        fuel_station_name=data.fuel_station_name,
        slip_id=data.slip_id,
    )
    db.add(fuel_log)

    if data.odometer_reading > vehicle.current_odometer:
        vehicle.current_odometer = data.odometer_reading
        vehicle.updated_by = created_by

    db.commit()
    db.refresh(fuel_log)
    return fuel_log


def get_fuel_log(
    db: Session, org_id: uuid.UUID, fuel_log_id: uuid.UUID, driver_id_filter: uuid.UUID | None = None
) -> FuelLog:
    stmt = select(FuelLog).where(
        FuelLog.id == fuel_log_id, FuelLog.organization_id == org_id, FuelLog.is_deleted.is_(False)
    )
    if driver_id_filter is not None:
        stmt = stmt.where(FuelLog.driver_id == driver_id_filter)
    fuel_log = db.execute(stmt).scalar_one_or_none()
    if fuel_log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fuel log not found")
    return fuel_log


def list_fuel_logs(
    db: Session,
    org_id: uuid.UUID,
    *,
    vehicle_id: uuid.UUID | None = None,
    driver_id: uuid.UUID | None = None,
    date_from: date_type | None = None,
    date_to: date_type | None = None,
    driver_id_filter: uuid.UUID | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[FuelLog]:
    stmt = select(FuelLog).where(FuelLog.organization_id == org_id, FuelLog.is_deleted.is_(False))
    if driver_id_filter is not None:
        stmt = stmt.where(FuelLog.driver_id == driver_id_filter)
    if vehicle_id is not None:
        stmt = stmt.where(FuelLog.vehicle_id == vehicle_id)
    if driver_id is not None:
        stmt = stmt.where(FuelLog.driver_id == driver_id)
    if date_from is not None:
        stmt = stmt.where(FuelLog.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(FuelLog.date <= date_to)
    stmt = stmt.order_by(FuelLog.date.asc(), FuelLog.created_at.asc()).offset(skip).limit(limit)
    return list(db.execute(stmt).scalars())


def update_fuel_log(
    db: Session,
    org_id: uuid.UUID,
    fuel_log_id: uuid.UUID,
    data: FuelLogUpdate,
    updated_by: uuid.UUID,
    driver_id_filter: uuid.UUID | None = None,
) -> FuelLog:
    """
    Recomputes cost_per_km/is_anomalous for THIS log only, using the same rule as
    create. Does NOT cascade to the chronologically-next log even though this
    edit may change what that log's 'previous' delta should have been --
    computed values are frozen at their own write time by design (see
    backendPlan.md's "Computed fields on create, not on read"), not a bug to fix.
    """
    fuel_log = get_fuel_log(db, org_id, fuel_log_id, driver_id_filter=driver_id_filter)

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(fuel_log, field, value)

    cost_per_km, is_anomalous = _compute_cost_per_km_and_anomaly(
        db,
        org_id,
        fuel_log.vehicle_id,
        fuel_log.date,
        fuel_log.odometer_reading,
        fuel_log.total_cost,
        exclude_id=fuel_log.id,
    )
    fuel_log.cost_per_km = cost_per_km
    fuel_log.is_anomalous = is_anomalous
    fuel_log.updated_by = updated_by

    vehicle = _get_vehicle_or_404(db, org_id, fuel_log.vehicle_id)
    if fuel_log.odometer_reading > vehicle.current_odometer:
        vehicle.current_odometer = fuel_log.odometer_reading
        vehicle.updated_by = updated_by

    db.commit()
    db.refresh(fuel_log)
    return fuel_log


def _store_receipt_file(fuel_log_id: uuid.UUID, filename: str, content: bytes) -> str:
    settings = get_settings()
    directory = Path(settings.upload_dir) / "fuel_receipts" / str(fuel_log_id)
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name or "receipt"  # strip any path components
    destination = directory / safe_name
    destination.write_bytes(content)
    return str(destination)


def attach_receipt(
    db: Session,
    org_id: uuid.UUID,
    fuel_log_id: uuid.UUID,
    file: UploadFile,
    uploaded_by: uuid.UUID,
    driver_id_filter: uuid.UUID | None = None,
) -> FuelReceipt:
    """Stores the file and its status only -- never parses its contents. That's
    ai_agents' job, via a separate mechanism that flips upload_status later."""
    fuel_log = get_fuel_log(db, org_id, fuel_log_id, driver_id_filter=driver_id_filter)

    existing = db.execute(
        select(FuelReceipt).where(FuelReceipt.fuel_log_id == fuel_log.id, FuelReceipt.is_deleted.is_(False))
    ).scalar_one_or_none()
    if existing is not None:
        raise _DUPLICATE_RECEIPT_ERROR

    if file.content_type not in _ALLOWED_RECEIPT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported receipt file type")

    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded receipt file is empty")

    file_path = _store_receipt_file(fuel_log.id, file.filename or "receipt", content)

    receipt = FuelReceipt(
        id=uuid.uuid4(),
        organization_id=org_id,
        created_by=uploaded_by,
        fuel_log_id=fuel_log.id,
        file_path=file_path,
        file_type=file.content_type,
        upload_status=FuelReceiptUploadStatus.pending,
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


def get_monthly_summary(db: Session, org_id: uuid.UUID, month: str | None) -> FuelSummaryResponse:
    """Read-only aggregation. Reused as-is by the Problem 5 dashboard service --
    do not duplicate this query there."""
    if month is None:
        today = datetime.now(timezone.utc).date()
        month = f"{today.year:04d}-{today.month:02d}"
    year, month_num = (int(part) for part in month.split("-"))
    period_start = date_type(year, month_num, 1)
    period_end = date_type(year, month_num, calendar.monthrange(year, month_num)[1])

    filters = (
        FuelLog.organization_id == org_id,
        FuelLog.is_deleted.is_(False),
        FuelLog.date >= period_start,
        FuelLog.date <= period_end,
    )

    # Postgres's AVG() on a NUMERIC(10,4) column expands to a much wider scale --
    # cast back to the column's own precision so responses are consistently formatted.
    avg_expr = cast(func.avg(FuelLog.cost_per_km), Numeric(10, 4))
    total_liters_expr = func.coalesce(func.sum(FuelLog.liters_filled), 0)

    total_cost, total_liters, avg_cost_per_km = db.execute(
        select(func.coalesce(func.sum(FuelLog.total_cost), 0), total_liters_expr, avg_expr).where(*filters)
    ).one()

    by_vehicle_rows = db.execute(
        select(
            FuelLog.vehicle_id,
            func.sum(FuelLog.total_cost),
            total_liters_expr,
            avg_expr,
            func.count(FuelLog.id),
            func.min(FuelLog.date),
            func.max(FuelLog.date),
        )
        .where(*filters)
        .group_by(FuelLog.vehicle_id)
    ).all()

    vehicle_ids = [row[0] for row in by_vehicle_rows]
    vehicles = (
        {v.id: v for v in db.execute(select(Vehicle).where(Vehicle.id.in_(vehicle_ids))).scalars()} if vehicle_ids else {}
    )
    drivers_by_vehicle: dict[uuid.UUID, list[str]] = {}
    if vehicle_ids:
        driver_rows = db.execute(
            select(FuelLog.vehicle_id, Driver.full_name)
            .join(Driver, Driver.id == FuelLog.driver_id)
            .where(*filters)
            .distinct()
            .order_by(Driver.full_name)
        ).all()
        for vid, name in driver_rows:
            drivers_by_vehicle.setdefault(vid, []).append(name)

    return FuelSummaryResponse(
        month=month,
        total_cost=total_cost,
        total_liters=total_liters,
        avg_cost_per_km=avg_cost_per_km,
        period_start=period_start,
        period_end=period_end,
        generated_at=datetime.now(timezone.utc),
        by_vehicle=[
            VehicleFuelSummary(
                vehicle_id=vehicle_id,
                plate_number=vehicles[vehicle_id].plate_number if vehicle_id in vehicles else None,
                vehicle_name=f"{vehicles[vehicle_id].make} {vehicles[vehicle_id].model}" if vehicle_id in vehicles else None,
                driver_names=drivers_by_vehicle.get(vehicle_id, []),
                total_cost=vtotal,
                total_liters=vliters,
                avg_cost_per_km=vavg,
                fill_count=fill_count,
                first_fill_date=first_date,
                last_fill_date=last_date,
            )
            for vehicle_id, vtotal, vliters, vavg, fill_count, first_date, last_date in by_vehicle_rows
        ],
    )


def get_fuel_cost_trend(db: Session, org_id: uuid.UUID, months: int = 12) -> list[tuple[str, Decimal, Decimal | None]]:
    """
    Fleet-wide monthly totals for the trailing `months` months (oldest first,
    ending with the current month). Every month appears even with zero fuel
    logs (total_cost=0, avg_cost_per_km=None) -- a plain GROUP BY would
    silently skip empty months, so the full month spine is built in Python and
    left-merged with one aggregate query, rather than calling
    get_monthly_summary once per month (which the Spec 05 plan explicitly says
    to avoid, to not pay for `months` round trips).

    Returns [(month, total_cost, avg_cost_per_km), ...]; used by
    dashboard_service.get_fuel_trends, not exposed as its own route.
    """
    today = datetime.now(timezone.utc).date()
    month_keys: list[str] = []
    year, month_num = today.year, today.month
    for _ in range(months):
        month_keys.append(f"{year:04d}-{month_num:02d}")
        month_num -= 1
        if month_num == 0:
            month_num = 12
            year -= 1
    month_keys.reverse()

    earliest_year, earliest_month = (int(part) for part in month_keys[0].split("-"))
    earliest_start = date_type(earliest_year, earliest_month, 1)

    avg_expr = cast(func.avg(FuelLog.cost_per_km), Numeric(10, 4))
    month_expr = func.to_char(FuelLog.date, "YYYY-MM")

    rows = db.execute(
        select(month_expr.label("month"), func.coalesce(func.sum(FuelLog.total_cost), 0), avg_expr)
        .where(FuelLog.organization_id == org_id, FuelLog.is_deleted.is_(False), FuelLog.date >= earliest_start)
        .group_by(month_expr)
    ).all()
    by_month = {month: (total_cost, avg_cost_per_km) for month, total_cost, avg_cost_per_km in rows}

    return [(key, *by_month.get(key, (Decimal("0"), None))) for key in month_keys]


def get_vehicle_cost_per_km_periods(
    db: Session, org_id: uuid.UUID, vehicle_id: uuid.UUID, as_of: date_type | None = None
) -> tuple[Decimal | None, Decimal | None]:
    """
    Returns (current_3mo_avg, prior_3mo_avg) of cost_per_km for one vehicle --
    the trailing ROLLING_WINDOW_MONTHS vs. the ROLLING_WINDOW_MONTHS before
    that, reusing the same window length as the anomaly-detection rolling
    average above. Either half is None if it has no non-null cost_per_km
    readings in that window. Used by dashboard_service's fleet-health
    fuel-efficiency signal, not exposed as its own route.
    """
    if as_of is None:
        as_of = datetime.now(timezone.utc).date()
    current_start = _months_before(as_of, ROLLING_WINDOW_MONTHS)
    prior_start = _months_before(current_start, ROLLING_WINDOW_MONTHS)

    def _avg(start: date_type, end: date_type) -> Decimal | None:
        return db.execute(
            select(cast(func.avg(FuelLog.cost_per_km), Numeric(10, 4))).where(
                FuelLog.organization_id == org_id,
                FuelLog.vehicle_id == vehicle_id,
                FuelLog.is_deleted.is_(False),
                FuelLog.cost_per_km.is_not(None),
                FuelLog.date >= start,
                FuelLog.date < end,
            )
        ).scalar_one()

    return _avg(current_start, as_of), _avg(prior_start, current_start)
