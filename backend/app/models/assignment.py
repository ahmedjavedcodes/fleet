import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import VehicleCondition
from app.models.mixins import AuditMixin, OrgScopedMixin


class VehicleAssignment(Base, OrgScopedMixin, AuditMixin):
    """Point-in-time custody record. released_at IS NULL means the assignment
    is currently active -- the sole source of truth for "who has this vehicle
    right now", never a separate status flag on Vehicle/Driver."""

    __tablename__ = "vehicle_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id"), nullable=False, index=True
    )
    driver_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drivers.id"), nullable=False, index=True
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    start_odometer: Mapped[int] = mapped_column(Integer, nullable=False)
    end_odometer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    take_condition: Mapped[VehicleCondition] = mapped_column(SAEnum(VehicleCondition, name="vehicle_condition"), nullable=False)
    leave_condition: Mapped[VehicleCondition | None] = mapped_column(
        SAEnum(VehicleCondition, name="vehicle_condition"), nullable=True
    )
    take_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    leave_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
