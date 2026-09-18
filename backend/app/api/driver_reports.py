import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_driver_profile, require_role
from app.models.driver import Driver
from app.models.enums import UserRole, VehicleCondition
from app.models.user import User
from app.schemas.accountability import DriverReportCreate, DriverReportResponse
from app.services import driver_report_service

router = APIRouter(prefix="/api/v1/driver-reports", tags=["driver-reports"])

# DriverReport: admin full, fleet_manager read all, driver own only, mechanic none.
# No PUT/PATCH/DELETE route in this router -- append-only by design (see
# backendPlan.md Problem 4). Do not add one.
_WRITE_ROLES = (UserRole.admin, UserRole.driver)
_READ_ROLES = (UserRole.admin, UserRole.fleet_manager, UserRole.driver)


def _driver_row_filter(current_user: User, driver_profile: Driver | None) -> uuid.UUID | None:
    if current_user.role != UserRole.driver:
        return None
    if driver_profile is None:
        return uuid.uuid4()
    return driver_profile.id


@router.post("", response_model=DriverReportResponse, status_code=status.HTTP_201_CREATED)
def create_driver_report(
    data: DriverReportCreate,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> DriverReportResponse:
    report = driver_report_service.create_driver_report(db, current_user.organization_id, data, current_user.id)
    return DriverReportResponse.model_validate(report)


@router.get("", response_model=list[DriverReportResponse])
def list_driver_reports(
    driver_id: uuid.UUID | None = None,
    vehicle_id: uuid.UUID | None = None,
    condition: VehicleCondition | None = None,
    current_user: User = Depends(require_role(*_READ_ROLES)),
    driver_profile: Driver | None = Depends(get_current_driver_profile),
    db: Session = Depends(get_db),
) -> list[DriverReportResponse]:
    reports = driver_report_service.list_driver_reports(
        db,
        current_user.organization_id,
        driver_id=driver_id,
        vehicle_id=vehicle_id,
        condition=condition,
        driver_id_filter=_driver_row_filter(current_user, driver_profile),
    )
    return [DriverReportResponse.model_validate(r) for r in reports]


@router.get("/{report_id}", response_model=DriverReportResponse)
def get_driver_report(
    report_id: uuid.UUID,
    current_user: User = Depends(require_role(*_READ_ROLES)),
    driver_profile: Driver | None = Depends(get_current_driver_profile),
    db: Session = Depends(get_db),
) -> DriverReportResponse:
    report = driver_report_service.get_driver_report(
        db, current_user.organization_id, report_id, driver_id_filter=_driver_row_filter(current_user, driver_profile)
    )
    return DriverReportResponse.model_validate(report)
