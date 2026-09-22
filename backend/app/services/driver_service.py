import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.driver import Driver
from app.models.user import User
from app.schemas.driver import DriverCreate, DriverUpdate


def _validate_user_link(db: Session, org_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    if user_id is None:
        return
    user = db.get(User, user_id)
    if user is None or user.organization_id != org_id or user.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Linked user not found")


def create_driver(db: Session, org_id: uuid.UUID, data: DriverCreate, created_by: uuid.UUID) -> Driver:
    _validate_user_link(db, org_id, data.user_id)
    driver = Driver(id=uuid.uuid4(), organization_id=org_id, created_by=created_by, **data.model_dump())
    db.add(driver)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This user is already linked to another driver profile"
        ) from exc
    db.refresh(driver)
    return driver


def get_driver(db: Session, org_id: uuid.UUID, driver_id: uuid.UUID) -> Driver:
    driver = db.execute(
        select(Driver).where(
            Driver.id == driver_id,
            Driver.organization_id == org_id,
            Driver.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if driver is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found")
    return driver


def list_drivers(db: Session, org_id: uuid.UUID) -> list[Driver]:
    stmt = select(Driver).where(Driver.organization_id == org_id, Driver.is_deleted.is_(False))
    return list(db.execute(stmt).scalars())


def update_driver(
    db: Session, org_id: uuid.UUID, driver_id: uuid.UUID, data: DriverUpdate, updated_by: uuid.UUID
) -> Driver:
    driver = get_driver(db, org_id, driver_id)
    updates = data.model_dump(exclude_unset=True)
    if "user_id" in updates:
        _validate_user_link(db, org_id, updates["user_id"])
    for field, value in updates.items():
        setattr(driver, field, value)
    driver.updated_by = updated_by
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This user is already linked to another driver profile"
        ) from exc
    db.refresh(driver)
    return driver


def delete_driver(db: Session, org_id: uuid.UUID, driver_id: uuid.UUID, deleted_by: uuid.UUID) -> None:
    driver = get_driver(db, org_id, driver_id)
    driver.is_deleted = True
    driver.deleted_at = datetime.now(timezone.utc)
    driver.updated_by = deleted_by
    db.commit()
