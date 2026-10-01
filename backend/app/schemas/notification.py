import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models.enums import NotificationType


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    message: str
    type: NotificationType
    is_read: bool
    created_at: datetime
    # "incident": derived at read time from an unresolved incident (see notification_service.list_feed), not a stored
    # notification: it has no read state (always is_read=True), cannot be marked read, and links to incident_id.
    source: Literal["notification", "incident"] = "notification"
    incident_id: uuid.UUID | None = None
