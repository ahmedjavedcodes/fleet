import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict

from app.models.enums import DriverStatus


class DriverBase(BaseModel):
    full_name: str
    license_number: str
    license_expiry: date
    phone: str
    status: DriverStatus = DriverStatus.active


class DriverCreate(DriverBase):
    # Settable only by admin/fleet_manager (enforced by route RBAC, not here) --
    # links an existing User to this Driver profile. Never set by the driver themself.
    user_id: uuid.UUID | None = None


class DriverUpdate(BaseModel):
    full_name: str | None = None
    license_number: str | None = None
    license_expiry: date | None = None
    phone: str | None = None
    status: DriverStatus | None = None
    user_id: uuid.UUID | None = None


class DriverResponse(DriverBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID | None
