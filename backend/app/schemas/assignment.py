import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.enums import VehicleCondition


class VehicleAssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    driver_id: uuid.UUID
    assigned_at: datetime
    start_odometer: int = Field(gt=0)
    take_condition: VehicleCondition
    take_notes: str | None = None


class VehicleReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    released_at: datetime
    end_odometer: int = Field(gt=0)
    leave_condition: VehicleCondition
    leave_notes: str | None = None


class VehicleAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vehicle_id: uuid.UUID
    driver_id: uuid.UUID
    assigned_at: datetime
    released_at: datetime | None
    start_odometer: int
    end_odometer: int | None
    take_condition: VehicleCondition
    leave_condition: VehicleCondition | None
    take_notes: str | None
    leave_notes: str | None
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration_hours(self) -> float | None:
        """None while the assignment is still active (released_at is None) --
        never computed against "now", since that would make a GET response's
        value change on every call for an active assignment."""
        if self.released_at is None:
            return None
        return round((self.released_at - self.assigned_at).total_seconds() / 3600, 2)


class DriverAssignmentHistoryResponse(BaseModel):
    driver_id: uuid.UUID
    current_assignment: VehicleAssignmentResponse | None
    total_vehicles_driven: int
    history: list[VehicleAssignmentResponse]
