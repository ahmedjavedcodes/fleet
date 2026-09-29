import uuid
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import ServiceScale, ServiceType
from app.schemas.common import VehicleDriverRefs


def _normalize_service_types(values: dict) -> dict:
    """Accept the legacy single `service_type` as shorthand for `service_types`,
    de-duplicating while preserving order. The first entry is the primary service."""
    if isinstance(values, dict) and "service_types" not in values and values.get("service_type") is not None:
        values = {**values, "service_types": [values["service_type"]]}
        values.pop("service_type", None)
    if isinstance(values, dict) and values.get("service_types") is not None:
        seen: list = []
        for item in values["service_types"]:
            if item not in seen:
                seen.append(item)
        values = {**values, "service_types": seen}
    return values


class MaintenanceLogCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: uuid.UUID
    date: date_type
    odometer_at_service: int = Field(gt=0)
    # One or more services performed in this visit (legacy `service_type` is still
    # accepted as shorthand for a single-element list).
    service_types: list[ServiceType] = Field(min_length=1)
    service_scale: ServiceScale = ServiceScale.minor
    # The driver who brought the vehicle in.
    driver_id: uuid.UUID | None = None
    description: str | None = None
    cost: Decimal | None = Field(default=None, ge=0)
    mechanic_name: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_service_type(cls, values):
        return _normalize_service_types(values)


class MaintenanceLogUpdate(BaseModel):
    """Same fields as create, all optional. Unlike FuelLog, there is no
    freeze-on-edit rule here -- next_due_km/next_due_date are selectively
    recomputed (see maintenance_service.update_maintenance_log)."""

    model_config = ConfigDict(extra="forbid")

    date: date_type | None = None
    odometer_at_service: int | None = Field(default=None, gt=0)
    service_types: list[ServiceType] | None = Field(default=None, min_length=1)
    service_scale: ServiceScale | None = None
    driver_id: uuid.UUID | None = None
    description: str | None = None
    cost: Decimal | None = Field(default=None, ge=0)
    mechanic_name: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_service_type(cls, values):
        return _normalize_service_types(values)


class PartUsed(BaseModel):
    part_id: uuid.UUID
    qty: int = Field(gt=0)


class MechanicReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagnostic_notes: str | None = None
    findings: str | None = None
    actions_taken: str | None = None
    parts_used: list[PartUsed] = Field(default_factory=list)
    recommendations: str | None = None


class LowStockAlert(BaseModel):
    part_id: uuid.UUID
    low_stock_alert: bool = True


class MechanicReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    maintenance_log_id: uuid.UUID
    diagnostic_notes: str | None
    findings: str | None
    actions_taken: str | None
    parts_used: list[PartUsed]
    recommendations: str | None
    # Only populated on the create response (echoed from the stock-decrement
    # call); empty on later GETs -- alerts are a point-in-time creation signal,
    # not a stored attribute of the report itself.
    low_stock_alerts: list[LowStockAlert] = Field(default_factory=list)


class MaintenanceLogResponse(VehicleDriverRefs):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vehicle_id: uuid.UUID
    date: date_type
    odometer_at_service: int
    # Primary (first) service, kept for consumers that only need one.
    service_type: ServiceType
    service_types: list[ServiceType]
    service_scale: ServiceScale
    driver_id: uuid.UUID | None
    description: str | None
    cost: Decimal | None
    mechanic_name: str | None
    next_due_km: int | None
    next_due_date: date_type | None
    created_at: datetime
    mechanic_report: MechanicReportResponse | None = None


class UpcomingMaintenanceItem(BaseModel):
    # service_type added for Spec 05's maintenance calendar (which needs to
    # say WHICH service is due, not just when) -- also just genuinely useful
    # on this endpoint itself, which the plan's schema omitted.
    vehicle_id: uuid.UUID
    plate_number: str
    service_type: ServiceType
    vehicle_name: str | None = None
    # Driver who brought the vehicle in for the last service of this type, and when.
    driver_name: str | None = None
    last_service_date: date_type | None = None
    service_scale: ServiceScale | None = None
    next_due_km: int | None
    next_due_date: date_type | None
    current_odometer: int
    km_remaining: int | None


class OverdueMaintenanceItem(BaseModel):
    vehicle_id: uuid.UUID
    plate_number: str
    service_type: ServiceType
    vehicle_name: str | None = None
    # Driver who brought the vehicle in for the last service of this type, and when.
    driver_name: str | None = None
    last_service_date: date_type | None = None
    service_scale: ServiceScale | None = None
    next_due_km: int | None
    next_due_date: date_type | None
    current_odometer: int
    km_remaining: int | None
