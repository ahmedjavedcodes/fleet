from fastapi import APIRouter, Depends, Query, Response
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


# Paged lists: `limit`/`offset` cut the result in the database and the unpaged total comes back in X-Total-Count.
# Without `limit` the whole list is returned, which is what the AI agents' tools rely on.
TOTAL_COUNT_HEADER = "X-Total-Count"


@router.get("/maintenance-calendar", response_model=MaintenanceCalendarResponse)
def get_maintenance_calendar(
    response: Response,
    window_days: int = Query(default=30, ge=1, le=365),
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_role(*_ROLES)),
    db: Session = Depends(get_db),
) -> MaintenanceCalendarResponse:
    items, total = dashboard_service.get_maintenance_calendar_page(
        db, current_user.organization_id, window_days=window_days, limit=limit, offset=offset
    )
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return items


@router.get("/fleet-health", response_model=FleetHealthResponse)
def get_fleet_health(
    response: Response,
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_role(*_ROLES)),
    db: Session = Depends(get_db),
) -> FleetHealthResponse:
    """With `limit`: worst health first, one page. Without: every scored vehicle."""
    items, total = dashboard_service.get_fleet_health_page(db, current_user.organization_id, limit=limit, offset=offset)
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return items
