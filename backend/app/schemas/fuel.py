import uuid
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import FuelReceiptUploadStatus
from app.schemas.common import VehicleDriverRefs

# Note: the type is imported as `date_type` (not `date`) because several fields
# below are named `date` with a default value -- `date: date | None = None`
# self-shadows, since Python binds the class attribute `date = None` *before*
# evaluating the `date | None` annotation, turning it into `None | None`.


class FuelLogCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: uuid.UUID
    driver_id: uuid.UUID | None = None
    date: date_type
    odometer_reading: int = Field(gt=0)
    liters_filled: Decimal = Field(gt=0)
    price_per_liter: Decimal = Field(gt=0)
    total_cost: Decimal = Field(gt=0)
    notes: str | None = None
    po_number: str | None = None
    payment_method: str | None = None
    card_used: str | None = None
    fuel_station_name: str | None = None
    slip_id: str | None = None


class FuelLogUpdate(BaseModel):
    """vehicle_id is deliberately not editable -- reassigning a fuel log to a
    different vehicle would need to re-run the neighbor lookup and side effects
    against two vehicles, an edge case not covered by the spec; editing amounts
    to deleting and recreating the log against the correct vehicle instead."""

    model_config = ConfigDict(extra="forbid")

    driver_id: uuid.UUID | None = None
    date: date_type | None = None
    odometer_reading: int | None = Field(default=None, gt=0)
    liters_filled: Decimal | None = Field(default=None, gt=0)
    price_per_liter: Decimal | None = Field(default=None, gt=0)
    total_cost: Decimal | None = Field(default=None, gt=0)
    notes: str | None = None
    po_number: str | None = None
    payment_method: str | None = None
    card_used: str | None = None
    fuel_station_name: str | None = None
    slip_id: str | None = None


class FuelReceiptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    file_path: str
    file_type: str
    upload_status: FuelReceiptUploadStatus
    parsed_data: dict | None


class FuelLogResponse(VehicleDriverRefs):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vehicle_id: uuid.UUID
    driver_id: uuid.UUID | None
    date: date_type
    odometer_reading: int
    liters_filled: Decimal
    price_per_liter: Decimal
    total_cost: Decimal
    cost_per_km: Decimal | None
    is_anomalous: bool
    notes: str | None
    po_number: str | None
    payment_method: str | None
    card_used: str | None
    fuel_station_name: str | None
    slip_id: str | None
    created_at: datetime
    receipt: FuelReceiptResponse | None = None


class VehicleFuelSummary(BaseModel):
    vehicle_id: uuid.UUID
    plate_number: str | None = None
    vehicle_name: str | None = None
    # Distinct drivers who fuelled this vehicle in the period.
    driver_names: list[str] = Field(default_factory=list)
    first_fill_date: date_type | None = None
    last_fill_date: date_type | None = None
    fill_count: int = 0
    total_cost: Decimal
    total_liters: Decimal
    avg_cost_per_km: Decimal | None


class FuelSummaryResponse(BaseModel):
    month: str
    period_start: date_type | None = None
    period_end: date_type | None = None
    generated_at: datetime | None = None
    total_cost: Decimal
    total_liters: Decimal
    avg_cost_per_km: Decimal | None
    by_vehicle: list[VehicleFuelSummary]
