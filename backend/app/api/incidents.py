import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_driver_profile, require_role
from app.models.driver import Driver
from app.models.enums import IncidentResolutionStatus, IncidentSeverity, IncidentType, UserRole
from app.models.user import User
from app.schemas.accountability import IncidentLogCreate, IncidentLogResolutionUpdate, IncidentLogResponse
from app.services import incident_service, notification_service

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])

# IncidentLog is not in the Spec 00 permission matrix -- inferred from
# backendPlan.md's "manager or driver logs an incident" narrative:
# admin/fleet_manager/driver can create and read; resolution updates are
# admin/fleet_manager only (a manager action, not a driver one). mechanic has
# no stated role anywhere in the source material, so no access. Flagged as an
# inference to confirm, not a settled rule (see plans/04 §4, specs/04 §4.8).
_CREATE_READ_ROLES = (UserRole.admin, UserRole.fleet_manager, UserRole.driver)
_RESOLVE_ROLES = (UserRole.admin, UserRole.fleet_manager)


def _driver_row_filter(current_user: User, driver_profile: Driver | None) -> uuid.UUID | None:
    """Row-level restriction for a 'driver'-role caller: incidents where
    driver_id is their own. The plan flags an alternative (incidents on
    vehicles they've driven) as undecided; this picks the simpler option,
    consistent with the driver_id-based filtering used identically for
    TripLog/DriverReport elsewhere in this domain."""
    if current_user.role != UserRole.driver:
        return None
    if driver_profile is None:
        return uuid.uuid4()
    return driver_profile.id


@router.post("", response_model=IncidentLogResponse, status_code=status.HTTP_201_CREATED)
def create_incident(
    data: IncidentLogCreate,
    current_user: User = Depends(require_role(*_CREATE_READ_ROLES)),
    db: Session = Depends(get_db),
) -> IncidentLogResponse:
    incident = incident_service.create_incident(db, current_user.organization_id, data, current_user.id)
    # Tell every admin and fleet manager. Best-effort and after the commit: it can't fail the report.
    notification_service.notify_incident_reported(db, current_user.organization_id, incident)
    return IncidentLogResponse.model_validate(incident)


@router.get("", response_model=list[IncidentLogResponse])
def list_incidents(
    type: IncidentType | None = None,
    severity: IncidentSeverity | None = None,
    status: IncidentResolutionStatus | None = None,  # noqa: A002 -- shadows fastapi.status locally; not used below
    search: str | None = Query(default=None, max_length=100, description="Vehicle plate/make/model, driver name or description"),
    current_user: User = Depends(require_role(*_CREATE_READ_ROLES)),
    driver_profile: Driver | None = Depends(get_current_driver_profile),
    db: Session = Depends(get_db),
) -> list[IncidentLogResponse]:
    incidents = incident_service.list_incidents(
        db,
        current_user.organization_id,
        incident_type=type,
        severity=severity,
        resolution_status=status,
        driver_id_filter=_driver_row_filter(current_user, driver_profile),
        search=search,
    )
    return [IncidentLogResponse.model_validate(i) for i in incidents]


@router.get("/{incident_id}", response_model=IncidentLogResponse)
def get_incident(
    incident_id: uuid.UUID,
    current_user: User = Depends(require_role(*_CREATE_READ_ROLES)),
    driver_profile: Driver | None = Depends(get_current_driver_profile),
    db: Session = Depends(get_db),
) -> IncidentLogResponse:
    incident = incident_service.get_incident(
        db, current_user.organization_id, incident_id, driver_id_filter=_driver_row_filter(current_user, driver_profile)
    )
    return IncidentLogResponse.model_validate(incident)


@router.put("/{incident_id}", response_model=IncidentLogResponse)
def update_incident_resolution(
    incident_id: uuid.UUID,
    data: IncidentLogResolutionUpdate,
    current_user: User = Depends(require_role(*_RESOLVE_ROLES)),
    db: Session = Depends(get_db),
) -> IncidentLogResponse:
    incident = incident_service.update_incident_resolution(db, current_user.organization_id, incident_id, data, current_user.id)
    return IncidentLogResponse.model_validate(incident)
