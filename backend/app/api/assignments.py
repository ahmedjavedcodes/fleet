import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_driver_profile, require_role
from app.models.driver import Driver
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.assignment import (
    DriverAssignmentHistoryResponse,
    VehicleAssignmentResponse,
    VehicleAssignRequest,
    VehicleReleaseRequest,
)
from app.services import assignment_service

router = APIRouter(prefix="/api/v1", tags=["assignments"])

_WRITE_ROLES = (UserRole.admin, UserRole.fleet_manager)
# A driver may read their own custody history but not another driver's --
# enforced in the handler (same pattern as GET /drivers/{id}/timeline), not
# just via role gating.
_DRIVER_HISTORY_ROLES = (UserRole.admin, UserRole.fleet_manager, UserRole.driver)
_VEHICLE_HISTORY_ROLES = (UserRole.admin, UserRole.fleet_manager, UserRole.driver)


@router.post("/vehicles/{vehicle_id}/assign", response_model=VehicleAssignmentResponse, status_code=status.HTTP_201_CREATED)
def assign_vehicle(
    vehicle_id: uuid.UUID,
    data: VehicleAssignRequest,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> VehicleAssignmentResponse:
    assignment = assignment_service.assign_vehicle(db, current_user.organization_id, vehicle_id, data, current_user.id)
    return VehicleAssignmentResponse.model_validate(assignment)


@router.post("/vehicles/{vehicle_id}/release", response_model=VehicleAssignmentResponse)
def release_vehicle(
    vehicle_id: uuid.UUID,
    data: VehicleReleaseRequest,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> VehicleAssignmentResponse:
    assignment = assignment_service.release_vehicle(db, current_user.organization_id, vehicle_id, data, current_user.id)
    return VehicleAssignmentResponse.model_validate(assignment)


@router.get("/drivers/{driver_id}/assignments", response_model=DriverAssignmentHistoryResponse)
def get_driver_assignment_history(
    driver_id: uuid.UUID,
    current_user: User = Depends(require_role(*_DRIVER_HISTORY_ROLES)),
    driver_profile: Driver | None = Depends(get_current_driver_profile),
    db: Session = Depends(get_db),
) -> DriverAssignmentHistoryResponse:
    if current_user.role == UserRole.driver:
        if driver_profile is None or driver_profile.id != driver_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot view another driver's assignment history")
    return assignment_service.get_driver_assignment_history(db, current_user.organization_id, driver_id)


@router.get("/vehicles/{vehicle_id}/assignments", response_model=list[VehicleAssignmentResponse])
def get_vehicle_assignment_history(
    vehicle_id: uuid.UUID,
    target_date: date | None = Query(default=None),
    current_user: User = Depends(require_role(*_VEHICLE_HISTORY_ROLES)),
    db: Session = Depends(get_db),
) -> list[VehicleAssignmentResponse]:
    assignments = assignment_service.get_vehicle_assignment_history(
        db, current_user.organization_id, vehicle_id, target_date=target_date
    )
    return [VehicleAssignmentResponse.model_validate(a) for a in assignments]
