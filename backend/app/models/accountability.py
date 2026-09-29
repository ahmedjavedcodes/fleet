import uuid
from datetime import date as date_
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum as SAEnum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import IncidentResolutionStatus, IncidentSeverity, IncidentType, VehicleCondition
from app.models.mixins import AuditMixin, OrgScopedMixin, VehicleDriverRefMixin


class TripLog(Base, OrgScopedMixin, AuditMixin, VehicleDriverRefMixin):
    """The 'who had the vehicle when' record. Both ends of the trip are
    required at creation -- per a deliberate product decision, this backend
    does not support an in-progress trip state (no separate 'complete trip'
    endpoint), so distance_km is always computed, never null."""

    __tablename__ = "trip_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("drivers.id"), nullable=False, index=True)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vehicles.id"), nullable=False, index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    start_odometer: Mapped[int] = mapped_column(Integer, nullable=False)
    end_odometer: Mapped[int] = mapped_column(Integer, nullable=False)
    # Computed at write-time and frozen -- end_odometer - start_odometer.
    distance_km: Mapped[int] = mapped_column(Integer, nullable=False)
    fuel_consumed: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    vehicle: Mapped["Vehicle"] = relationship("Vehicle", lazy="joined", viewonly=True)
    driver: Mapped["Driver"] = relationship("Driver", lazy="joined", viewonly=True)


class DriverReport(Base, OrgScopedMixin, AuditMixin, VehicleDriverRefMixin):
    """The 'what condition was it in' record. Append-only by design -- no
    update path exists anywhere in the service layer, which is what keeps
    this audit evidence trustworthy. is_deleted/soft-delete still applies for
    moderation, but that's the only mutation this model ever receives."""

    __tablename__ = "driver_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("drivers.id"), nullable=False, index=True)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vehicles.id"), nullable=False, index=True)
    shift_date: Mapped[date_] = mapped_column(Date, nullable=False)
    vehicle_condition: Mapped[VehicleCondition] = mapped_column(SAEnum(VehicleCondition, name="vehicle_condition"), nullable=False)
    handover_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    issues_reported: Mapped[str | None] = mapped_column(Text, nullable=True)

    vehicle: Mapped["Vehicle"] = relationship("Vehicle", lazy="joined", viewonly=True)
    driver: Mapped["Driver"] = relationship("Driver", lazy="joined", viewonly=True)


class IncidentLog(Base, OrgScopedMixin, AuditMixin, VehicleDriverRefMixin):
    """The 'something went wrong' record. incident_type/date/severity/
    description/location_description/estimated_cost are immutable after
    creation -- only resolution_status/resolution_notes are ever writable,
    and only via the dedicated resolution-update schema/route."""

    __tablename__ = "incident_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("drivers.id"), nullable=True)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vehicles.id"), nullable=False, index=True)
    incident_type: Mapped[IncidentType] = mapped_column(SAEnum(IncidentType, name="incident_type"), nullable=False)
    # Full timestamp of the incident. Nullable for rows that pre-date the column (backfilled
    # from `date` by the migration); `date` stays the immutable calendar-day key.
    incident_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    date: Mapped[date_] = mapped_column(Date, nullable=False)
    severity: Mapped[IncidentSeverity] = mapped_column(SAEnum(IncidentSeverity, name="incident_severity"), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_area: Mapped[str | None] = mapped_column(String(255), nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    resolution_status: Mapped[IncidentResolutionStatus] = mapped_column(
        SAEnum(IncidentResolutionStatus, name="incident_resolution_status"),
        default=IncidentResolutionStatus.open,
        server_default=IncidentResolutionStatus.open.value,
        nullable=False,
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    vehicle: Mapped["Vehicle"] = relationship("Vehicle", lazy="joined", viewonly=True)
    driver: Mapped["Driver | None"] = relationship("Driver", lazy="joined", viewonly=True)
