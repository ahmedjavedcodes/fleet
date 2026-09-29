import uuid
from datetime import date as date_
from decimal import Decimal

from sqlalchemy import Boolean, Date, Enum as SAEnum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import FuelReceiptUploadStatus
from app.models.mixins import AuditMixin, OrgScopedMixin, VehicleDriverRefMixin


class FuelLog(Base, OrgScopedMixin, AuditMixin, VehicleDriverRefMixin):
    __tablename__ = "fuel_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id"), nullable=False, index=True
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("drivers.id"), nullable=True)
    date: Mapped[date_] = mapped_column(Date, nullable=False)
    odometer_reading: Mapped[int] = mapped_column(Integer, nullable=False)
    liters_filled: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    price_per_liter: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Computed at write-time and frozen -- never recalculated when read. See
    # fuel_service.py for the computation; this column only ever stores the result.
    cost_per_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    is_anomalous: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Slip/receipt details captured off the physical fuel slip.
    po_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    card_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fuel_station_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    slip_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    receipt: Mapped["FuelReceipt | None"] = relationship(back_populates="fuel_log", uselist=False)
    vehicle: Mapped["Vehicle"] = relationship("Vehicle", lazy="joined", viewonly=True)
    driver: Mapped["Driver | None"] = relationship("Driver", lazy="joined", viewonly=True)


class FuelReceipt(Base, OrgScopedMixin, AuditMixin):
    __tablename__ = "fuel_receipts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fuel_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_logs.id"), unique=True, nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # AI module flips this later (pending -> parsed/failed) -- backend only ever
    # writes 'pending' and never reads/writes parsed_data's structured content.
    upload_status: Mapped[FuelReceiptUploadStatus] = mapped_column(
        SAEnum(FuelReceiptUploadStatus, name="fuel_receipt_upload_status"),
        default=FuelReceiptUploadStatus.pending,
        server_default=FuelReceiptUploadStatus.pending.value,
        nullable=False,
    )
    parsed_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    fuel_log: Mapped["FuelLog"] = relationship(back_populates="receipt")
