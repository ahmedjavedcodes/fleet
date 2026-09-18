import uuid
from datetime import date as date_type
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.accountability import TripLog
from app.models.vehicle import Vehicle
from app.schemas.accountability import TripLogCreate

_INVALID_ODOMETER_ERROR = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST, detail="end_odometer must be greater than or equal to start_odometer"
)


def _get_vehicle_or_404(db: Session, org_id: uuid.UUID, vehicle_id: uuid.UUID) -> Vehicle:
    vehicle = db.execute(
        select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.organization_id == org_id, Vehicle.is_deleted.is_(False))
    ).scalar_one_or_none()
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    return vehicle


def create_trip(db: Session, org_id: uuid.UUID, data: TripLogCreate, created_by: uuid.UUID) -> TripLog:
    """
    Single transaction: compute distance_km, insert the trip, and update
    Vehicle.current_odometer as a side effect -- all or nothing. Same pattern
    as FuelLog (Spec 01).
    """
    vehicle = _get_vehicle_or_404(db, org_id, data.vehicle_id)

    if data.end_odometer < data.start_odometer:
        raise _INVALID_ODOMETER_ERROR
    distance_km = data.end_odometer - data.start_odometer

    trip = TripLog(
        id=uuid.uuid4(),
        organization_id=org_id,
        created_by=created_by,
        driver_id=data.driver_id,
        vehicle_id=data.vehicle_id,
        start_time=data.start_time,
        end_time=data.end_time,
        start_odometer=data.start_odometer,
        end_odometer=data.end_odometer,
        distance_km=distance_km,
        fuel_consumed=data.fuel_consumed,
        notes=data.notes,
    )
    db.add(trip)

    if data.end_odometer > vehicle.current_odometer:
        vehicle.current_odometer = data.end_odometer
        vehicle.updated_by = created_by

    db.commit()
    db.refresh(trip)
    return trip


def get_trip(db: Session, org_id: uuid.UUID, trip_id: uuid.UUID, driver_id_filter: uuid.UUID | None = None) -> TripLog:
    stmt = select(TripLog).where(TripLog.id == trip_id, TripLog.organization_id == org_id, TripLog.is_deleted.is_(False))
    if driver_id_filter is not None:
        stmt = stmt.where(TripLog.driver_id == driver_id_filter)
    trip = db.execute(stmt).scalar_one_or_none()
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
    return trip


def list_trips(
    db: Session,
    org_id: uuid.UUID,
    *,
    driver_id: uuid.UUID | None = None,
    vehicle_id: uuid.UUID | None = None,
    date_from: date_type | None = None,
    date_to: date_type | None = None,
    driver_id_filter: uuid.UUID | None = None,
) -> list[TripLog]:
    stmt = select(TripLog).where(TripLog.organization_id == org_id, TripLog.is_deleted.is_(False))
    if driver_id_filter is not None:
        stmt = stmt.where(TripLog.driver_id == driver_id_filter)
    if driver_id is not None:
        stmt = stmt.where(TripLog.driver_id == driver_id)
    if vehicle_id is not None:
        stmt = stmt.where(TripLog.vehicle_id == vehicle_id)
    if date_from is not None:
        stmt = stmt.where(TripLog.start_time >= datetime.combine(date_from, datetime.min.time()))
    if date_to is not None:
        stmt = stmt.where(TripLog.start_time <= datetime.combine(date_to, datetime.max.time()))
    stmt = stmt.order_by(TripLog.start_time.desc())
    return list(db.execute(stmt).scalars())
