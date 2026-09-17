import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_driver_profile, require_role
from app.models.driver import Driver
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.fuel import FuelLogCreate, FuelLogResponse, FuelLogUpdate, FuelReceiptResponse, FuelSummaryResponse
from app.services import fuel_service

router = APIRouter(prefix="/api/v1/fuel", tags=["fuel"])

# FuelLog: admin full, fleet_manager read all, driver own only, mechanic none.
_WRITE_ROLES = (UserRole.admin, UserRole.driver)
_READ_ROLES = (UserRole.admin, UserRole.fleet_manager, UserRole.driver)
_SUMMARY_ROLES = (UserRole.admin, UserRole.fleet_manager)


def _driver_row_filter(current_user: User, driver_profile: Driver | None) -> uuid.UUID | None:
    """None -> no row-level restriction (admin/fleet_manager). For a 'driver'-role
    caller, their own Driver.id -- or, if unlinked, a random UUID that matches no
    row, so list/get naturally come back empty/404 without a separate branch."""
    if current_user.role != UserRole.driver:
        return None
    if driver_profile is None:
        return uuid.uuid4()
    return driver_profile.id


@router.post("", response_model=FuelLogResponse, status_code=status.HTTP_201_CREATED)
def create_fuel_log(
    data: FuelLogCreate,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    driver_profile: Driver | None = Depends(get_current_driver_profile),
    db: Session = Depends(get_db),
) -> FuelLogResponse:
    driver_override = None
    if current_user.role == UserRole.driver:
        if driver_profile is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="No driver profile is linked to this account",
            )
        driver_override = driver_profile.id

    fuel_log = fuel_service.create_fuel_log(
        db, current_user.organization_id, data, current_user.id, driver_id_override=driver_override
    )
    return FuelLogResponse.model_validate(fuel_log)


@router.get("", response_model=list[FuelLogResponse])
def list_fuel_logs(
    vehicle_id: uuid.UUID | None = None,
    driver_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    current_user: User = Depends(require_role(*_READ_ROLES)),
    driver_profile: Driver | None = Depends(get_current_driver_profile),
    db: Session = Depends(get_db),
) -> list[FuelLogResponse]:
    logs = fuel_service.list_fuel_logs(
        db,
        current_user.organization_id,
        vehicle_id=vehicle_id,
        driver_id=driver_id,
        date_from=date_from,
        date_to=date_to,
        driver_id_filter=_driver_row_filter(current_user, driver_profile),
    )
    return [FuelLogResponse.model_validate(log) for log in logs]


@router.get("/summary", response_model=FuelSummaryResponse)
def get_monthly_summary(
    month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    current_user: User = Depends(require_role(*_SUMMARY_ROLES)),
    db: Session = Depends(get_db),
) -> FuelSummaryResponse:
    return fuel_service.get_monthly_summary(db, current_user.organization_id, month)


@router.get("/{fuel_log_id}", response_model=FuelLogResponse)
def get_fuel_log(
    fuel_log_id: uuid.UUID,
    current_user: User = Depends(require_role(*_READ_ROLES)),
    driver_profile: Driver | None = Depends(get_current_driver_profile),
    db: Session = Depends(get_db),
) -> FuelLogResponse:
    fuel_log = fuel_service.get_fuel_log(
        db, current_user.organization_id, fuel_log_id, driver_id_filter=_driver_row_filter(current_user, driver_profile)
    )
    return FuelLogResponse.model_validate(fuel_log)


@router.put("/{fuel_log_id}", response_model=FuelLogResponse)
def update_fuel_log(
    fuel_log_id: uuid.UUID,
    data: FuelLogUpdate,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    driver_profile: Driver | None = Depends(get_current_driver_profile),
    db: Session = Depends(get_db),
) -> FuelLogResponse:
    if current_user.role == UserRole.driver:
        # A driver may edit their own log but never reassign it to someone else.
        payload = data.model_dump(exclude_unset=True)
        payload.pop("driver_id", None)
        data = FuelLogUpdate(**payload)

    fuel_log = fuel_service.update_fuel_log(
        db,
        current_user.organization_id,
        fuel_log_id,
        data,
        current_user.id,
        driver_id_filter=_driver_row_filter(current_user, driver_profile),
    )
    return FuelLogResponse.model_validate(fuel_log)


@router.post("/{fuel_log_id}/receipt", response_model=FuelReceiptResponse, status_code=status.HTTP_201_CREATED)
def attach_receipt(
    fuel_log_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    driver_profile: Driver | None = Depends(get_current_driver_profile),
    db: Session = Depends(get_db),
) -> FuelReceiptResponse:
    receipt = fuel_service.attach_receipt(
        db,
        current_user.organization_id,
        fuel_log_id,
        file,
        current_user.id,
        driver_id_filter=_driver_row_filter(current_user, driver_profile),
    )
    return FuelReceiptResponse.model_validate(receipt)
