import uuid

from sqlalchemy import Enum as SAEnum, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import VehicleFuelType, VehicleStatus
from app.models.mixins import AuditMixin, OrgScopedMixin


class Vehicle(Base, OrgScopedMixin, AuditMixin):
    __tablename__ = "vehicles"
    __table_args__ = (UniqueConstraint("organization_id", "plate_number", name="uq_vehicles_org_plate"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plate_number: Mapped[str] = mapped_column(String(50), nullable=False)
    make: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    vin: Mapped[str] = mapped_column(String(17), unique=True, nullable=False)
    current_odometer: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    fuel_type: Mapped[VehicleFuelType] = mapped_column(
        SAEnum(VehicleFuelType, name="vehicle_fuel_type"), nullable=False
    )
    status: Mapped[VehicleStatus] = mapped_column(
        SAEnum(VehicleStatus, name="vehicle_status"),
        default=VehicleStatus.active,
        server_default=VehicleStatus.active.value,
        nullable=False,
    )
    service_interval_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    service_interval_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
