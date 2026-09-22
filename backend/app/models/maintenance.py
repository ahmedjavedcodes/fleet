import uuid
from datetime import date as date_
from decimal import Decimal

from sqlalchemy import Date, Enum as SAEnum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ServiceType
from app.models.mixins import AuditMixin, OrgScopedMixin


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


class MaintenanceLog(Base, OrgScopedMixin, AuditMixin):
    __tablename__ = "maintenance_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id"), nullable=False, index=True
    )
    date: Mapped[date_] = mapped_column(Date, nullable=False)
    odometer_at_service: Mapped[int] = mapped_column(Integer, nullable=False)
    service_type: Mapped[ServiceType] = mapped_column(SAEnum(ServiceType, name="service_type"), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Free text, not a User FK -- there is no structured Mechanic entity (see
    # backendPlan.md Foundation layer "Open design decisions").
    mechanic_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Computed at write-time and frozen on create; selectively recomputed on
    # update only when odometer_at_service or date changes (see maintenance_service.py).
    next_due_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_due_date: Mapped[date_ | None] = mapped_column(Date, nullable=True)

    mechanic_report: Mapped["MechanicReport | None"] = relationship(back_populates="maintenance_log", uselist=False)


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
