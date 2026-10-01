import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.enums import NotificationType
from app.models.user import User
from app.schemas.notification import NotificationResponse
from app.services import notification_service

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

# Every role has notifications, but only ever its own -- there is no way to read
# or change another user's, so no role gating is needed here.


@router.get("", response_model=list[NotificationResponse])
def list_notifications(
    type: NotificationType | None = None,
    unread_only: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[NotificationResponse]:
    """Stored notifications plus, for admins and fleet managers, the unresolved incidents as warnings/events."""
    return notification_service.list_feed(db, current_user, type=type, unread_only=unread_only, limit=limit, offset=offset)


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
def mark_notification_read(
    notification_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> NotificationResponse:
    return NotificationResponse.model_validate(notification_service.mark_read(db, current_user, notification_id))
