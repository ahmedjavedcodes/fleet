import uuid
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ServiceType


class MaintenanceLogCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: uuid.UUID
    date: date_type
    odometer_at_service: int = Field(gt=0)
    service_type: ServiceType
    description: str | None = None
    cost: Decimal | None = Field(default=None, ge=0)
    mechanic_name: str | None = None


class MaintenanceLogUpdate(BaseModel):
    """Same fields as create, all optional. Unlike FuelLog, there is no
    freeze-on-edit rule here -- next_due_km/next_due_date are selectively
    recomputed (see maintenance_service.update_maintenance_log)."""

    model_config = ConfigDict(extra="forbid")

    date: date_type | None = None
    odometer_at_service: int | None = Field(default=None, gt=0)
    service_type: ServiceType | None = None
    description: str | None = None
    cost: Decimal | None = Field(default=None, ge=0)
    mechanic_name: str | None = None


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


class MaintenanceLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vehicle_id: uuid.UUID
    date: date_type
    odometer_at_service: int
    service_type: ServiceType
    description: str | None
    cost: Decimal | None
    mechanic_name: str | None
    next_due_km: int | None
    next_due_date: date_type | None
    created_at: datetime
    mechanic_report: MechanicReportResponse | None = None


class UpcomingMaintenanceItem(BaseModel):
    vehicle_id: uuid.UUID
    plate_number: str
    next_due_km: int | None
    next_due_date: date_type | None
    current_odometer: int
    km_remaining: int | None


class OverdueMaintenanceItem(BaseModel):
    vehicle_id: uuid.UUID
    plate_number: str
    next_due_km: int | None
    next_due_date: date_type | None
    current_odometer: int
    km_remaining: int | None
