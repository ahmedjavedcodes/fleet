import uuid

from pydantic import BaseModel, ConfigDict

from app.models.enums import VehicleFuelType, VehicleOwnershipType, VehicleStatus


class VehicleBase(BaseModel):
    plate_number: str
    make: str
    model: str
    year: int
    vin: str
    fuel_type: VehicleFuelType
    status: VehicleStatus = VehicleStatus.active
    service_interval_km: int | None = None
    service_interval_months: int | None = None
    engine_number: str | None = None
    chassis_number: str | None = None
    ownership_type: VehicleOwnershipType = VehicleOwnershipType.owner


class VehicleCreate(VehicleBase):
    current_odometer: int = 0


class VehicleUpdate(BaseModel):
    plate_number: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = None
    vin: str | None = None
    current_odometer: int | None = None
    fuel_type: VehicleFuelType | None = None
    status: VehicleStatus | None = None
    service_interval_km: int | None = None
    service_interval_months: int | None = None
    engine_number: str | None = None
    chassis_number: str | None = None
    ownership_type: VehicleOwnershipType | None = None


class VehicleResponse(VehicleBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    current_odometer: int
    # Set server-side from the authenticated user on create; not accepted in requests.
    added_by: uuid.UUID | None = None
