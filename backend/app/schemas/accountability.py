import uuid
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import IncidentResolutionStatus, IncidentSeverity, IncidentType, VehicleCondition
from app.schemas.common import VehicleDriverRefs

# --- TripLog -------------------------------------------------------------------


class TripLogCreate(BaseModel):
    """Both ends of the trip are required -- this backend does not support an
    in-progress trip state (deliberate product decision, no separate
    'complete trip' endpoint exists)."""

    model_config = ConfigDict(extra="forbid")

    driver_id: uuid.UUID
    vehicle_id: uuid.UUID
    start_time: datetime
    end_time: datetime
    start_odometer: int = Field(gt=0)
    end_odometer: int = Field(gt=0)
    fuel_consumed: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None


class TripLogResponse(VehicleDriverRefs):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    driver_id: uuid.UUID
    vehicle_id: uuid.UUID
    start_time: datetime
    end_time: datetime
    start_odometer: int
    end_odometer: int
    distance_km: int
    fuel_consumed: Decimal | None
    notes: str | None
    created_at: datetime


# --- DriverReport (append-only: create + response only, no update schema) ----------


class DriverReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    driver_id: uuid.UUID
    vehicle_id: uuid.UUID
    shift_date: date_type
    vehicle_condition: VehicleCondition
    handover_notes: str | None = None
    issues_reported: str | None = None


class DriverReportResponse(VehicleDriverRefs):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    driver_id: uuid.UUID
    vehicle_id: uuid.UUID
    shift_date: date_type
    vehicle_condition: VehicleCondition
    handover_notes: str | None
    issues_reported: str | None
    created_at: datetime


# --- IncidentLog -----------------------------------------------------------------


class IncidentLogCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    driver_id: uuid.UUID | None = None
    vehicle_id: uuid.UUID
    incident_type: IncidentType
    # At least one of date/incident_time is required; date is derived from incident_time
    # when omitted, so callers with a full timestamp never have to send both.
    date: date_type | None = None
    incident_time: datetime | None = None
    severity: IncidentSeverity
    description: str
    location_description: str | None = None
    location_area: str | None = None
    remarks: str | None = None
    attachment_url: str | None = None
    estimated_cost: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _require_date_or_time(self) -> "IncidentLogCreate":
        if self.date is None:
            if self.incident_time is None:
                raise ValueError("Either date or incident_time is required")
            self.date = self.incident_time.date()
        return self


class IncidentLogResolutionUpdate(BaseModel):
    """Only resolution_status/resolution_notes -- this schema's shape is what
    enforces immutability of the original fields at the API boundary, not
    just a service-layer check. description/severity/etc. are not fields
    here at all, so a request including them is rejected by extra='forbid'."""

    model_config = ConfigDict(extra="forbid")

    resolution_status: IncidentResolutionStatus
    resolution_notes: str | None = None


class IncidentLogResponse(VehicleDriverRefs):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    driver_id: uuid.UUID | None
    vehicle_id: uuid.UUID
    incident_type: IncidentType
    date: date_type
    incident_time: datetime | None
    severity: IncidentSeverity
    description: str
    location_description: str | None
    location_area: str | None
    remarks: str | None
    attachment_url: str | None
    estimated_cost: Decimal | None
    resolution_status: IncidentResolutionStatus
    resolution_notes: str | None
    created_at: datetime


# --- Timeline ------------------------------------------------------------------


class TimelineEntry(BaseModel):
    record_type: Literal["trip", "report", "incident"]
    id: uuid.UUID
    date: datetime
    summary: dict


# A plain array, consistent with the FleetComplianceMatrixResponse convention
# used elsewhere in this API.
TimelineResponse = list[TimelineEntry]
