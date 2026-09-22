import uuid

from sqlalchemy import DateTime, cast, func, literal, select, union_all
from sqlalchemy.orm import Session

from app.models.accountability import DriverReport, IncidentLog, TripLog
from app.schemas.accountability import TimelineEntry


def _build_timeline_query(org_id: uuid.UUID, *, vehicle_id: uuid.UUID | None = None, driver_id: uuid.UUID | None = None):
    """
    A single SQL UNION ALL across trip_logs, driver_reports, incident_logs,
    each branch projecting a literal record_type discriminator plus a
    jsonb_build_object summary of its own type-specific fields -- so
    ordering and interleaving happen entirely in SQL (per CLAUDE.md 'Timeline
    as a UNION ALL query, not application-layer stitching'), never stitched
    together from three separate application-layer queries.

    Exactly one of vehicle_id/driver_id is expected to be provided by the
    caller; the same extra filter is applied identically to all three branches.
    """

    def _scope(stmt, model):
        stmt = stmt.where(model.organization_id == org_id, model.is_deleted.is_(False))
        if vehicle_id is not None:
            stmt = stmt.where(model.vehicle_id == vehicle_id)
        if driver_id is not None:
            stmt = stmt.where(model.driver_id == driver_id)
        return stmt

    trip_select = _scope(
        select(
            literal("trip").label("record_type"),
            TripLog.id.label("id"),
            TripLog.start_time.label("event_date"),
            func.jsonb_build_object(
                "driver_id", TripLog.driver_id,
                "vehicle_id", TripLog.vehicle_id,
                "start_time", TripLog.start_time,
                "end_time", TripLog.end_time,
                "start_odometer", TripLog.start_odometer,
                "end_odometer", TripLog.end_odometer,
                "distance_km", TripLog.distance_km,
                "fuel_consumed", TripLog.fuel_consumed,
                "notes", TripLog.notes,
            ).label("summary"),
        ),
        TripLog,
    )

    report_select = _scope(
        select(
            literal("report").label("record_type"),
            DriverReport.id.label("id"),
            cast(DriverReport.shift_date, DateTime(timezone=True)).label("event_date"),
            func.jsonb_build_object(
                "driver_id", DriverReport.driver_id,
                "vehicle_id", DriverReport.vehicle_id,
                "shift_date", DriverReport.shift_date,
                "vehicle_condition", DriverReport.vehicle_condition,
                "handover_notes", DriverReport.handover_notes,
                "issues_reported", DriverReport.issues_reported,
            ).label("summary"),
        ),
        DriverReport,
    )

    incident_select = _scope(
        select(
            literal("incident").label("record_type"),
            IncidentLog.id.label("id"),
            cast(IncidentLog.date, DateTime(timezone=True)).label("event_date"),
            func.jsonb_build_object(
                "driver_id", IncidentLog.driver_id,
                "vehicle_id", IncidentLog.vehicle_id,
                "incident_type", IncidentLog.incident_type,
                "date", IncidentLog.date,
                "severity", IncidentLog.severity,
                "description", IncidentLog.description,
                "location_description", IncidentLog.location_description,
                "estimated_cost", IncidentLog.estimated_cost,
                "resolution_status", IncidentLog.resolution_status,
                "resolution_notes", IncidentLog.resolution_notes,
            ).label("summary"),
        ),
        IncidentLog,
    )

    union = union_all(trip_select, report_select, incident_select).subquery()
    # Stable secondary sort on id so two records sharing the exact same
    # event_date still return in a deterministic, repeatable order.
    return select(union).order_by(union.c.event_date.desc(), union.c.id.desc())


def get_vehicle_timeline(db: Session, org_id: uuid.UUID, vehicle_id: uuid.UUID) -> list[TimelineEntry]:
    stmt = _build_timeline_query(org_id, vehicle_id=vehicle_id)
    rows = db.execute(stmt).all()
    return [TimelineEntry(record_type=row.record_type, id=row.id, date=row.event_date, summary=row.summary) for row in rows]


def get_driver_timeline(db: Session, org_id: uuid.UUID, driver_id: uuid.UUID) -> list[TimelineEntry]:
    stmt = _build_timeline_query(org_id, driver_id=driver_id)
    rows = db.execute(stmt).all()
    return [TimelineEntry(record_type=row.record_type, id=row.id, date=row.event_date, summary=row.summary) for row in rows]
