import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


class AuditMixin:
    """created_by/updated_by are nullable on every model (not just User) so that the
    bootstrap admin created during org registration -- before any User row exists to
    attribute authorship to -- is simply the normal nullable case, not a special one."""

    @declared_attr
    def created_by(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @declared_attr
    def updated_by(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrgScopedMixin:
    @declared_attr
    def organization_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)


class VehicleDriverRefMixin:
    """Read-only flat accessors over the `vehicle`/`driver` relationships that
    the host model declares (lazy="joined"), so response schemas can expose
    plate/make/model/driver name via plain from_attributes without a second
    query. driver is optional on some models, hence the None guards."""

    @property
    def vehicle_plate(self) -> str | None:
        return self.vehicle.plate_number if getattr(self, "vehicle", None) is not None else None

    @property
    def vehicle_make(self) -> str | None:
        return self.vehicle.make if getattr(self, "vehicle", None) is not None else None

    @property
    def vehicle_model(self) -> str | None:
        return self.vehicle.model if getattr(self, "vehicle", None) is not None else None

    @property
    def vehicle_name(self) -> str | None:
        vehicle = getattr(self, "vehicle", None)
        return f"{vehicle.make} {vehicle.model}" if vehicle is not None else None

    @property
    def driver_name(self) -> str | None:
        driver = getattr(self, "driver", None)
        return driver.full_name if driver is not None else None
