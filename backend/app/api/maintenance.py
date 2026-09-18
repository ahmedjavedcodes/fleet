import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_role
from app.models.enums import ServiceType, UserRole
from app.models.user import User
from app.schemas.maintenance import (
    MaintenanceLogCreate,
    MaintenanceLogResponse,
    MaintenanceLogUpdate,
    MechanicReportCreate,
    MechanicReportResponse,
    OverdueMaintenanceItem,
    UpcomingMaintenanceItem,
)
from app.services import maintenance_service

router = APIRouter(prefix="/api/v1/maintenance", tags=["maintenance"])

# MaintenanceLog/MechanicReport: admin full, fleet_manager read all, driver
# none, mechanic own jobs. Row-level "own jobs" filtering for mechanic is a
# known, explicitly-flagged gap (see plans/03 §5) -- there is no reliable FK
# to filter on (MaintenanceLog.mechanic_name is free text), so mechanic is
# scoped to role-level access only here, not row-level, until that's resolved.
_FULL_WRITE_ROLES = (UserRole.admin, UserRole.mechanic)
_READ_ROLES = (UserRole.admin, UserRole.fleet_manager, UserRole.mechanic)
_FLEET_VIEW_ROLES = (UserRole.admin, UserRole.fleet_manager)


@router.post("", response_model=MaintenanceLogResponse, status_code=status.HTTP_201_CREATED)
def create_maintenance_log(
    data: MaintenanceLogCreate,
    current_user: User = Depends(require_role(*_FULL_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> MaintenanceLogResponse:
    log = maintenance_service.create_maintenance_log(db, current_user.organization_id, data, current_user.id)
    return MaintenanceLogResponse.model_validate(log)


@router.get("", response_model=list[MaintenanceLogResponse])
def list_maintenance_logs(
    vehicle_id: uuid.UUID | None = None,
    service_type: ServiceType | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    current_user: User = Depends(require_role(*_READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[MaintenanceLogResponse]:
    logs = maintenance_service.list_maintenance_logs(
        db,
        current_user.organization_id,
        vehicle_id=vehicle_id,
        service_type=service_type,
        date_from=date_from,
        date_to=date_to,
    )
    return [MaintenanceLogResponse.model_validate(log) for log in logs]


@router.get("/upcoming", response_model=list[UpcomingMaintenanceItem])
def list_upcoming(
    window_km: int = Query(default=1000, gt=0),
    current_user: User = Depends(require_role(*_FLEET_VIEW_ROLES)),
    db: Session = Depends(get_db),
) -> list[UpcomingMaintenanceItem]:
    return maintenance_service.list_upcoming(db, current_user.organization_id, window_km=window_km)


@router.get("/overdue", response_model=list[OverdueMaintenanceItem])
def list_overdue(
    current_user: User = Depends(require_role(*_FLEET_VIEW_ROLES)),
    db: Session = Depends(get_db),
) -> list[OverdueMaintenanceItem]:
    return maintenance_service.list_overdue(db, current_user.organization_id)


@router.get("/{log_id}", response_model=MaintenanceLogResponse)
def get_maintenance_log(
    log_id: uuid.UUID,
    current_user: User = Depends(require_role(*_READ_ROLES)),
    db: Session = Depends(get_db),
) -> MaintenanceLogResponse:
    log = maintenance_service.get_maintenance_log(db, current_user.organization_id, log_id)
    return MaintenanceLogResponse.model_validate(log)


@router.put("/{log_id}", response_model=MaintenanceLogResponse)
def update_maintenance_log(
    log_id: uuid.UUID,
    data: MaintenanceLogUpdate,
    current_user: User = Depends(require_role(*_FULL_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> MaintenanceLogResponse:
    log = maintenance_service.update_maintenance_log(db, current_user.organization_id, log_id, data, current_user.id)
    return MaintenanceLogResponse.model_validate(log)


@router.post("/{log_id}/mechanic-report", response_model=MechanicReportResponse, status_code=status.HTTP_201_CREATED)
def create_mechanic_report(
    log_id: uuid.UUID,
    data: MechanicReportCreate,
    current_user: User = Depends(require_role(*_FULL_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> MechanicReportResponse:
    report, alerts = maintenance_service.create_mechanic_report(db, current_user.organization_id, log_id, data, current_user.id)
    payload = MechanicReportResponse.model_validate(report).model_dump()
    payload["low_stock_alerts"] = alerts
    return MechanicReportResponse(**payload)
