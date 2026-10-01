import logging
import uuid
from datetime import datetime, time, timezone
from collections.abc import Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.accountability import IncidentLog
from app.models.enums import IncidentResolutionStatus, IncidentSeverity, NotificationType, UserRole
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import NotificationResponse

logger = logging.getLogger("fleet.notifications")

INCIDENT_RECIPIENT_ROLES = (UserRole.admin, UserRole.fleet_manager)
# Severe and critical incidents are warnings; minor/moderate ones are informational events.
_WARNING_SEVERITIES = (IncidentSeverity.severe, IncidentSeverity.critical)


def list_notifications(
    db: Session, user: User, *, type: NotificationType | None = None, unread_only: bool = False, limit: int = 100
) -> list[Notification]:
    """Only ever the caller's own notifications, newest first."""
    stmt = select(Notification).where(Notification.user_id == user.id)
    if type is not None:
        stmt = stmt.where(Notification.type == type)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id).limit(limit)
    return list(db.execute(stmt).scalars())


_UNRESOLVED = (IncidentResolutionStatus.open, IncidentResolutionStatus.investigating)
_EVENT_SEVERITIES = (IncidentSeverity.minor, IncidentSeverity.moderate)


def _incident_feed(db: Session, user: User, type: NotificationType | None, limit: int) -> list[NotificationResponse]:
    """The unresolved (open or investigating) incidents, as feed entries, newest first.

    Notifications are stored only when an incident is reported through the API, so incidents that arrived any other way
    (imports, bulk loads, anything older than the feature) never produced one, and the Warnings feed read "No warnings"
    while the dashboard counted hundreds of open incidents. This maps the incidents themselves: severe and critical
    ones are warnings, minor and moderate ones are events, matching notify_incident_reported. Only admins and fleet
    managers (the roles that are told about incidents) see them. They carry no read state, so they are always read."""
    if user.role not in INCIDENT_RECIPIENT_ROLES:
        return []
    stmt = select(IncidentLog).where(
        IncidentLog.organization_id == user.organization_id,
        IncidentLog.is_deleted.is_(False),
        IncidentLog.resolution_status.in_(_UNRESOLVED),
        # An incident this user already has a stored notification for is listed once, as that notification.
        IncidentLog.id.not_in(
            select(Notification.incident_id).where(Notification.user_id == user.id, Notification.incident_id.is_not(None))
        ),
    )
    if type == NotificationType.warning:
        stmt = stmt.where(IncidentLog.severity.in_(_WARNING_SEVERITIES))
    elif type == NotificationType.event:
        stmt = stmt.where(IncidentLog.severity.in_(_EVENT_SEVERITIES))
    stmt = stmt.order_by(IncidentLog.date.desc(), IncidentLog.created_at.desc(), IncidentLog.id).limit(limit)

    feed: list[NotificationResponse] = []
    for incident in db.execute(stmt).scalars():
        plate = incident.vehicle_plate or "a vehicle"
        who = f" by {incident.driver_name}" if incident.driver_name else ""
        severity = incident.severity.value
        happened = incident.incident_time or datetime.combine(incident.date, time(0, 0), tzinfo=timezone.utc)
        feed.append(
            NotificationResponse(
                id=incident.id,
                title=f"Open {severity} incident on {plate}",
                message=f"{incident.description} (reported{who} on {incident.date}; {incident.resolution_status.value}).",
                type=NotificationType.warning if incident.severity in _WARNING_SEVERITIES else NotificationType.event,
                is_read=True,
                created_at=happened,
                source="incident",
                incident_id=incident.id,
            )
        )
    return feed


def list_feed(
    db: Session, user: User, *, type: NotificationType | None = None, unread_only: bool = False, limit: int = 100, offset: int = 0
) -> list[NotificationResponse]:
    """The caller's stored notifications merged with the incident-derived entries, newest first, one page.

    Each source is read only as far as this page needs (limit + offset rows) in SQL, so the cost does not grow with
    how many incidents exist. unread_only skips the derived entries, which are never unread."""
    window = limit + offset
    stored = [NotificationResponse.model_validate(n) for n in list_notifications(db, user, type=type, unread_only=unread_only, limit=window)]
    derived = [] if unread_only else _incident_feed(db, user, type, window)
    merged = sorted(stored + derived, key=lambda n: n.created_at, reverse=True)
    return merged[offset : offset + limit]


def mark_read(db: Session, user: User, notification_id: uuid.UUID) -> Notification:
    """Idempotent. Another user's notification is a 404, not a 403, so its existence isn't disclosed."""
    notification = db.execute(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == user.id)
    ).scalar_one_or_none()
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    if not notification.is_read:
        notification.is_read = True
        db.commit()
        db.refresh(notification)
    return notification


def notify_roles(
    db: Session,
    org_id: uuid.UUID,
    roles: Sequence[UserRole],
    *,
    title: str,
    message: str,
    type: NotificationType,
    incident_id: uuid.UUID | None = None,
) -> list[Notification]:
    """One notification per active user in the organization holding any of `roles`."""
    recipients = db.execute(
        select(User).where(User.organization_id == org_id, User.role.in_(roles), User.is_active.is_(True))
    ).scalars()
    notifications = [Notification(id=uuid.uuid4(), user_id=u.id, title=title, message=message, type=type, incident_id=incident_id) for u in recipients]
    db.add_all(notifications)
    db.commit()
    return notifications


def notify_incident_reported(db: Session, org_id: uuid.UUID, incident: IncidentLog) -> list[Notification]:
    """Tell every admin and fleet manager that an incident was reported.

    Runs after the incident is committed and never raises: a notification problem
    must not fail, or roll back, someone reporting an incident."""
    try:
        plate = incident.vehicle_plate or "a vehicle"
        who = f" by {incident.driver_name}" if incident.driver_name else ""
        severity = incident.severity.value
        return notify_roles(
            db,
            org_id,
            INCIDENT_RECIPIENT_ROLES,
            title=f"New {severity} incident on {plate}",
            message=f"{incident.description} (reported{who} on {incident.date}).",
            type=NotificationType.warning if incident.severity in _WARNING_SEVERITIES else NotificationType.event,
            incident_id=incident.id,
        )
    except Exception:
        db.rollback()
        logger.exception("Could not create incident notifications for incident %s", incident.id)
        return []
