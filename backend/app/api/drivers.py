import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_driver_profile, require_role
from app.models.driver import Driver
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.accountability import TimelineResponse
from app.schemas.driver import DriverCreate, DriverResponse, DriverUpdate
from app.services import driver_service, timeline_service

router = APIRouter(prefix="/api/v1/drivers", tags=["drivers"])

_WRITE_ROLES = (UserRole.admin, UserRole.fleet_manager)
_READ_ROLES = (UserRole.admin, UserRole.fleet_manager, UserRole.driver, UserRole.mechanic)
# The driver timeline exposes another person's handover/incident history, not
# just vehicle state -- mechanic is excluded here even though it can read
# plain Driver records above, and a driver may only request their own id
# (enforced in the handler, not just via role gating).
_TIMELINE_ROLES = (UserRole.admin, UserRole.fleet_manager, UserRole.driver)


@router.post("", response_model=DriverResponse, status_code=status.HTTP_201_CREATED)
def create_driver(
    data: DriverCreate,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> DriverResponse:
    driver = driver_service.create_driver(db, current_user.organization_id, data, current_user.id)
    return DriverResponse.model_validate(driver)


@router.get("", response_model=list[DriverResponse])
def list_drivers(
    current_user: User = Depends(require_role(*_READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[DriverResponse]:
    drivers = driver_service.list_drivers(db, current_user.organization_id)
    return [DriverResponse.model_validate(d) for d in drivers]


@router.get("/{driver_id}", response_model=DriverResponse)
def get_driver(
    driver_id: uuid.UUID,
    current_user: User = Depends(require_role(*_READ_ROLES)),
    db: Session = Depends(get_db),
) -> DriverResponse:
    driver = driver_service.get_driver(db, current_user.organization_id, driver_id)
    return DriverResponse.model_validate(driver)


@router.put("/{driver_id}", response_model=DriverResponse)
def update_driver(
    driver_id: uuid.UUID,
    data: DriverUpdate,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> DriverResponse:
    driver = driver_service.update_driver(db, current_user.organization_id, driver_id, data, current_user.id)
    return DriverResponse.model_validate(driver)


@router.delete("/{driver_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_driver(
    driver_id: uuid.UUID,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> None:
    driver_service.delete_driver(db, current_user.organization_id, driver_id, current_user.id)


@router.get("/{driver_id}/timeline", response_model=TimelineResponse)
def get_driver_timeline(
    driver_id: uuid.UUID,
    current_user: User = Depends(require_role(*_TIMELINE_ROLES)),
    driver_profile: Driver | None = Depends(get_current_driver_profile),
    db: Session = Depends(get_db),
) -> TimelineResponse:
    if current_user.role == UserRole.driver:
        if driver_profile is None or driver_profile.id != driver_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot view another driver's timeline")
    return timeline_service.get_driver_timeline(db, current_user.organization_id, driver_id)
