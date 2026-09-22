import uuid
from datetime import date

from sqlalchemy import Date, Enum as SAEnum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import DriverStatus
from app.models.mixins import AuditMixin, OrgScopedMixin


class Driver(Base, OrgScopedMixin, AuditMixin):
    """Operational profile, deliberately separate from User. user_id is nullable --
    a driver may never get app login access -- and unique when set, so at most one
    Driver links to a given User."""

    __tablename__ = "drivers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=True
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    license_number: Mapped[str] = mapped_column(String(100), nullable=False)
    license_expiry: Mapped[date] = mapped_column(Date, nullable=False)
    phone: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[DriverStatus] = mapped_column(
        SAEnum(DriverStatus, name="driver_status"),
        default=DriverStatus.active,
        server_default=DriverStatus.active.value,
        nullable=False,
    )
