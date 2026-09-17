import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.enums import UserRole


class UserResponse(BaseModel):
    """Never includes hashed_password. role/organization_id are read-only after
    creation -- there is no UserUpdate schema in this layer."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    email: EmailStr
    full_name: str
    phone: str | None
    role: UserRole
    is_active: bool
    last_login_at: datetime | None
