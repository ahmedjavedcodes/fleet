import logging
import uuid
from collections.abc import Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.accountability import IncidentLog
from app.models.enums import IncidentSeverity, NotificationType, UserRole
from app.models.notification import Notification
from app.models.user import User

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
) -> list[Notification]:
    """One notification per active user in the organization holding any of `roles`."""
    recipients = db.execute(
        select(User).where(User.organization_id == org_id, User.role.in_(roles), User.is_active.is_(True))
    ).scalars()
    notifications = [Notification(id=uuid.uuid4(), user_id=u.id, title=title, message=message, type=type) for u in recipients]
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
        )
    except Exception:
        db.rollback()
        logger.exception("Could not create incident notifications for incident %s", incident.id)
        return []
