from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_role
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.dashboard import (
    DashboardSummaryResponse,
    FuelTrendsResponse,
    MaintenanceCalendarResponse,
    FleetHealthResponse,
)
from app.services import dashboard_service

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])

# Dashboard/insights: admin full, fleet_manager full, driver none, mechanic
# none. No row-level filtering anywhere -- every number here is fleet-wide by
# definition. All four routes are read-only and side-effect-free, which is
# what makes them safe to expose over MCP to ai_agents unmodified.
_ROLES = (UserRole.admin, UserRole.fleet_manager)


@router.get("/summary", response_model=DashboardSummaryResponse)
def get_summary(
    current_user: User = Depends(require_role(*_ROLES)),
    db: Session = Depends(get_db),
) -> DashboardSummaryResponse:
    return dashboard_service.get_summary(db, current_user.organization_id)


@router.get("/fuel-trends", response_model=FuelTrendsResponse)
def get_fuel_trends(
    months: int = Query(default=12, ge=1, le=24),
    current_user: User = Depends(require_role(*_ROLES)),
    db: Session = Depends(get_db),
) -> FuelTrendsResponse:
    return dashboard_service.get_fuel_trends(db, current_user.organization_id, months=months)


@router.get("/maintenance-calendar", response_model=MaintenanceCalendarResponse)
def get_maintenance_calendar(
    window_days: int = Query(default=30, ge=1, le=365),
    current_user: User = Depends(require_role(*_ROLES)),
    db: Session = Depends(get_db),
) -> MaintenanceCalendarResponse:
    return dashboard_service.get_maintenance_calendar(db, current_user.organization_id, window_days=window_days)


@router.get("/fleet-health", response_model=FleetHealthResponse)
def get_fleet_health(
    current_user: User = Depends(require_role(*_ROLES)),
    db: Session = Depends(get_db),
) -> FleetHealthResponse:
    return dashboard_service.get_fleet_health(db, current_user.organization_id)
