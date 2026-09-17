import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.vehicle import Vehicle
from app.schemas.vehicle import VehicleCreate, VehicleUpdate

_DUPLICATE_ERROR = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="A vehicle with this plate number or VIN already exists"
)


def create_vehicle(db: Session, org_id: uuid.UUID, data: VehicleCreate, created_by: uuid.UUID) -> Vehicle:
    vehicle = Vehicle(id=uuid.uuid4(), organization_id=org_id, created_by=created_by, **data.model_dump())
    db.add(vehicle)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _DUPLICATE_ERROR from exc
    db.refresh(vehicle)
    return vehicle


def get_vehicle(db: Session, org_id: uuid.UUID, vehicle_id: uuid.UUID) -> Vehicle:
    vehicle = db.execute(
        select(Vehicle).where(
            Vehicle.id == vehicle_id,
            Vehicle.organization_id == org_id,
            Vehicle.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    return vehicle


def list_vehicles(db: Session, org_id: uuid.UUID) -> list[Vehicle]:
    stmt = select(Vehicle).where(Vehicle.organization_id == org_id, Vehicle.is_deleted.is_(False))
    return list(db.execute(stmt).scalars())


def update_vehicle(
    db: Session, org_id: uuid.UUID, vehicle_id: uuid.UUID, data: VehicleUpdate, updated_by: uuid.UUID
) -> Vehicle:
    vehicle = get_vehicle(db, org_id, vehicle_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(vehicle, field, value)
    vehicle.updated_by = updated_by
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _DUPLICATE_ERROR from exc
    db.refresh(vehicle)
    return vehicle


def delete_vehicle(db: Session, org_id: uuid.UUID, vehicle_id: uuid.UUID, deleted_by: uuid.UUID) -> None:
    vehicle = get_vehicle(db, org_id, vehicle_id)
    vehicle.is_deleted = True
    vehicle.deleted_at = datetime.now(timezone.utc)
    vehicle.updated_by = deleted_by
    db.commit()
