import uuid
from datetime import date as date_type
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.accountability import IncidentLog
from app.models.enums import IncidentResolutionStatus, IncidentSeverity, IncidentType
from app.schemas.accountability import IncidentLogCreate, IncidentLogResolutionUpdate


def create_incident(db: Session, org_id: uuid.UUID, data: IncidentLogCreate, created_by: uuid.UUID) -> IncidentLog:
    incident = IncidentLog(id=uuid.uuid4(), organization_id=org_id, created_by=created_by, **data.model_dump())
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident


def get_incident(
    db: Session, org_id: uuid.UUID, incident_id: uuid.UUID, driver_id_filter: uuid.UUID | None = None
) -> IncidentLog:
    stmt = select(IncidentLog).where(
        IncidentLog.id == incident_id, IncidentLog.organization_id == org_id, IncidentLog.is_deleted.is_(False)
    )
    if driver_id_filter is not None:
        stmt = stmt.where(IncidentLog.driver_id == driver_id_filter)
    incident = db.execute(stmt).scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return incident


def list_incidents(
    db: Session,
    org_id: uuid.UUID,
    *,
    incident_type: IncidentType | None = None,
    severity: IncidentSeverity | None = None,
    resolution_status: IncidentResolutionStatus | None = None,
    driver_id_filter: uuid.UUID | None = None,
    search: str | None = None,
) -> list[IncidentLog]:
    stmt = select(IncidentLog).where(IncidentLog.organization_id == org_id, IncidentLog.is_deleted.is_(False))
    if search and search.strip():
        from app.models.driver import Driver
        from app.models.vehicle import Vehicle

        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            IncidentLog.description.icontains(search.strip(), autoescape=True)
            | IncidentLog.vehicle_id.in_(
                select(Vehicle.id).where(
                    Vehicle.plate_number.icontains(search.strip(), autoescape=True)
                    | Vehicle.make.icontains(search.strip(), autoescape=True)
                    | Vehicle.model.icontains(search.strip(), autoescape=True)
                )
            )
            | IncidentLog.driver_id.in_(select(Driver.id).where(Driver.full_name.icontains(search.strip(), autoescape=True)))
        )
    if driver_id_filter is not None:
        stmt = stmt.where(IncidentLog.driver_id == driver_id_filter)
    if incident_type is not None:
        stmt = stmt.where(IncidentLog.incident_type == incident_type)
    if severity is not None:
        stmt = stmt.where(IncidentLog.severity == severity)
    if resolution_status is not None:
        stmt = stmt.where(IncidentLog.resolution_status == resolution_status)
    stmt = stmt.order_by(IncidentLog.date.desc())
    return list(db.execute(stmt).scalars())


def update_incident_resolution(
    db: Session, org_id: uuid.UUID, incident_id: uuid.UUID, data: IncidentLogResolutionUpdate, updated_by: uuid.UUID
) -> IncidentLog:
    """Only ever touches resolution_status/resolution_notes -- enforced by the
    request schema's shape (IncidentLogResolutionUpdate has no other fields),
    and reinforced here by setting attributes explicitly rather than looping
    over an arbitrary model_dump(), so no other field could slip through even
    if the schema were ever loosened."""
    incident = get_incident(db, org_id, incident_id)
    incident.resolution_status = data.resolution_status
    incident.resolution_notes = data.resolution_notes
    incident.updated_by = updated_by
    db.commit()
    db.refresh(incident)
    return incident


# What the dashboard calls "open": not yet resolved or closed.
UNRESOLVED_STATUSES = (IncidentResolutionStatus.open, IncidentResolutionStatus.investigating)


def count_unresolved(db: Session, org_id: uuid.UUID) -> int:
    """SELECT COUNT(*) of open + investigating incidents: ix_incident_logs_org_status_severity serves it."""
    return db.execute(
        select(func.count(IncidentLog.id)).where(
            IncidentLog.organization_id == org_id,
            IncidentLog.is_deleted.is_(False),
            IncidentLog.resolution_status.in_(UNRESOLVED_STATUSES),
        )
    ).scalar_one()


def recent_incident_counts(db: Session, org_id: uuid.UUID, days: int = 90) -> dict[uuid.UUID, int]:
    """Trailing-`days` incident count per vehicle in ONE grouped query (vehicles with none are absent)."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date()
    rows = db.execute(
        select(IncidentLog.vehicle_id, func.count(IncidentLog.id))
        .where(IncidentLog.organization_id == org_id, IncidentLog.is_deleted.is_(False), IncidentLog.date >= since)
        .group_by(IncidentLog.vehicle_id)
    ).all()
    return {vehicle_id: count for vehicle_id, count in rows}


def count_recent_incidents_for_vehicle(db: Session, org_id: uuid.UUID, vehicle_id: uuid.UUID, days: int = 90) -> int:
    """Count of incidents in the trailing `days` days for one vehicle. Used by
    dashboard_service's fleet-health incident signal, not exposed as its own route."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date()
    return db.execute(
        select(func.count(IncidentLog.id)).where(
            IncidentLog.organization_id == org_id,
            IncidentLog.is_deleted.is_(False),
            IncidentLog.vehicle_id == vehicle_id,
            IncidentLog.date >= since,
        )
    ).scalar_one()
