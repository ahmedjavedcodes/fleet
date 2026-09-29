import uuid
from datetime import date as date_
from decimal import Decimal

from sqlalchemy import Date, Enum as SAEnum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ServiceScale, ServiceType
from app.models.mixins import AuditMixin, OrgScopedMixin, VehicleDriverRefMixin


class ComplianceRule(Base, OrgScopedMixin, AuditMixin):
    """The manufacturer's rule, scoped by make/model -- never by individual
    vehicle. Soft match against Vehicle.make/model, no FK."""

    __tablename__ = "compliance_rules"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "vehicle_make", "vehicle_model", "service_type", name="uq_compliance_rule_org_make_model_type"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vehicle_make: Mapped[str] = mapped_column(String(100), nullable=False)
    vehicle_model: Mapped[str] = mapped_column(String(100), nullable=False)
    service_type: Mapped[ServiceType] = mapped_column(SAEnum(ServiceType, name="service_type"), nullable=False)
    interval_km: Mapped[int] = mapped_column(Integer, nullable=False)
    interval_months: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Reference to a Document (manual PDF) -- informational, not a FK.
    source_document: Mapped[str | None] = mapped_column(String(500), nullable=True)


class MaintenanceLog(Base, OrgScopedMixin, AuditMixin, VehicleDriverRefMixin):
    __tablename__ = "maintenance_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id"), nullable=False, index=True
    )
    date: Mapped[date_] = mapped_column(Date, nullable=False)
    odometer_at_service: Mapped[int] = mapped_column(Integer, nullable=False)
    # Primary (first) service, kept in sync with `services` for consumers that
    # only need one -- the full set of services performed lives in `services`.
    service_type: Mapped[ServiceType] = mapped_column(SAEnum(ServiceType, name="service_type"), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Free text, not a User FK -- there is no structured Mechanic entity (see
    # backendPlan.md Foundation layer "Open design decisions").
    mechanic_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    service_scale: Mapped[ServiceScale] = mapped_column(
        SAEnum(ServiceScale, name="service_scale"),
        default=ServiceScale.minor,
        server_default=ServiceScale.minor.value,
        nullable=False,
    )
    # The driver who brought the vehicle in.
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drivers.id"), nullable=True, index=True
    )
    # Computed at write-time and frozen on create; selectively recomputed on
    # update only when odometer_at_service or date changes (see maintenance_service.py).
    next_due_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_due_date: Mapped[date_ | None] = mapped_column(Date, nullable=True)

    mechanic_report: Mapped["MechanicReport | None"] = relationship(back_populates="maintenance_log", uselist=False)
    services: Mapped[list["MaintenanceLogService"]] = relationship(
        back_populates="maintenance_log", cascade="all, delete-orphan", order_by="MaintenanceLogService.position", lazy="selectin"
    )
    vehicle: Mapped["Vehicle"] = relationship("Vehicle", lazy="joined", viewonly=True)
    driver: Mapped["Driver | None"] = relationship("Driver", lazy="joined", viewonly=True)

    def __init__(self, **kwargs) -> None:
        # Invariant: every log has at least one MaintenanceLogService row. Callers that
        # only know a single service_type (tests, seed scripts, legacy code paths) get
        # the matching row created for them.
        if "services" not in kwargs and kwargs.get("service_type") is not None:
            kwargs["services"] = [MaintenanceLogService(service_type=kwargs["service_type"], position=0)]
        super().__init__(**kwargs)

    @property
    def service_types(self) -> list[ServiceType]:
        return [s.service_type for s in self.services]


class MechanicReport(Base, OrgScopedMixin, AuditMixin):
    """The unstructured diagnostic record, 1:1 child of MaintenanceLog.
    Structured (queryable) fields stay on MaintenanceLog; free text lives here,
    stored verbatim for the AI module to vectorize later -- never analyzed here."""

    __tablename__ = "mechanic_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    maintenance_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("maintenance_logs.id"), unique=True, nullable=False
    )
    diagnostic_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    findings: Mapped[str | None] = mapped_column(Text, nullable=True)
    actions_taken: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Array of {part_id, qty} -- triggers the Plan 02 stock decrement, stored as-is.
    parts_used: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    recommendations: Mapped[str | None] = mapped_column(Text, nullable=True)

    maintenance_log: Mapped["MaintenanceLog"] = relationship(back_populates="mechanic_report")


class MaintenanceLogService(Base):
    """One service performed during a maintenance visit. A MaintenanceLog has one
    or more of these (e.g. oil change + brake service in the same visit); `position`
    preserves the order they were submitted in, with position 0 mirrored onto
    MaintenanceLog.service_type as the primary service."""

    __tablename__ = "maintenance_log_services"
    __table_args__ = (UniqueConstraint("maintenance_log_id", "service_type", name="uq_maintenance_log_service"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    maintenance_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("maintenance_logs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_type: Mapped[ServiceType] = mapped_column(SAEnum(ServiceType, name="service_type"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    maintenance_log: Mapped["MaintenanceLog"] = relationship(back_populates="services")
