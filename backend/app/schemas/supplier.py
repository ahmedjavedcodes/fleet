import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class SupplierBase(BaseModel):
    name: str
    contact_email: str | None = None
    phone: str | None = None
    avg_lead_time_days: int | None = None


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(BaseModel):
    name: str | None = None
    contact_email: str | None = None
    phone: str | None = None
    avg_lead_time_days: int | None = None


class SupplierResponse(SupplierBase):
    # reliability_score is response-only, never accepted on create/update --
    # it's computed in Plan 02, not this layer.
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    reliability_score: Decimal | None
