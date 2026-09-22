import uuid
from datetime import date as date_type
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ServiceType


class ComplianceRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_make: str
    vehicle_model: str
    service_type: ServiceType
    interval_km: int = Field(gt=0)
    interval_months: int = Field(gt=0)
    description: str | None = None
    source_document: str | None = None


class ComplianceRuleUpdate(BaseModel):
    """Interval fields only, per the plan -- vehicle_make/vehicle_model/
    service_type form the composite lookup key and are not editable here;
    changing them would silently reassign which vehicles the rule applies to."""

    model_config = ConfigDict(extra="forbid")

    interval_km: int | None = Field(default=None, gt=0)
    interval_months: int | None = Field(default=None, gt=0)
    description: str | None = None
    source_document: str | None = None


class ComplianceRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    vehicle_make: str
    vehicle_model: str
    service_type: ServiceType
    interval_km: int
    interval_months: int
    description: str | None
    source_document: str | None


ComplianceStatus = Literal["compliant", "due_soon", "overdue", "never_performed"]


class ComplianceStatusItem(BaseModel):
    rule: ComplianceRuleResponse
    status: ComplianceStatus
    km_remaining: int | None
    days_remaining: int | None
    last_service_date: date_type | None


class VehicleComplianceResponse(BaseModel):
    vehicle_id: uuid.UUID
    items: list[ComplianceStatusItem]


# A fleet-wide matrix is just a list of per-vehicle results -- matches the
# plain-array response_model convention used everywhere else in this API
# rather than introducing a wrapper object with no other purpose.
FleetComplianceMatrixResponse = list[VehicleComplianceResponse]
