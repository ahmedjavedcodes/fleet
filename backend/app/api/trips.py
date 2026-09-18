import uuid
from datetime import date

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_driver_profile, require_role
from app.models.driver import Driver
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.accountability import TripLogCreate, TripLogResponse
from app.services import trip_service

router = APIRouter(prefix="/api/v1/trips", tags=["trips"])

# TripLog: admin full, fleet_manager read all, driver own only, mechanic none.
_WRITE_ROLES = (UserRole.admin, UserRole.driver)
_READ_ROLES = (UserRole.admin, UserRole.fleet_manager, UserRole.driver)


def _driver_row_filter(current_user: User, driver_profile: Driver | None) -> uuid.UUID | None:
    """None -> no row-level restriction (admin/fleet_manager). For a
    'driver'-role caller, their own Driver.id -- or, if unlinked, a random
    UUID that matches no row, so list/get naturally come back empty/404."""
    if current_user.role != UserRole.driver:
        return None
    if driver_profile is None:
        return uuid.uuid4()
    return driver_profile.id


@router.post("", response_model=TripLogResponse, status_code=status.HTTP_201_CREATED)
def create_trip(
    data: TripLogCreate,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> TripLogResponse:
    trip = trip_service.create_trip(db, current_user.organization_id, data, current_user.id)
    return TripLogResponse.model_validate(trip)


@router.get("", response_model=list[TripLogResponse])
def list_trips(
    driver_id: uuid.UUID | None = None,
    vehicle_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    current_user: User = Depends(require_role(*_READ_ROLES)),
    driver_profile: Driver | None = Depends(get_current_driver_profile),
    db: Session = Depends(get_db),
) -> list[TripLogResponse]:
    trips = trip_service.list_trips(
        db,
        current_user.organization_id,
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        date_from=date_from,
        date_to=date_to,
        driver_id_filter=_driver_row_filter(current_user, driver_profile),
    )
    return [TripLogResponse.model_validate(t) for t in trips]


@router.get("/{trip_id}", response_model=TripLogResponse)
def get_trip(
    trip_id: uuid.UUID,
    current_user: User = Depends(require_role(*_READ_ROLES)),
    driver_profile: Driver | None = Depends(get_current_driver_profile),
    db: Session = Depends(get_db),
) -> TripLogResponse:
    trip = trip_service.get_trip(
        db, current_user.organization_id, trip_id, driver_id_filter=_driver_row_filter(current_user, driver_profile)
    )
    return TripLogResponse.model_validate(trip)
