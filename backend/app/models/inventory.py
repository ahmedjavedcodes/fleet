import uuid
from datetime import date as date_
from decimal import Decimal

from sqlalchemy import Date, Enum as SAEnum, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import PurchaseOrderStatus
from app.models.mixins import AuditMixin, OrgScopedMixin


class PartsInventory(Base, OrgScopedMixin, AuditMixin):
    __tablename__ = "parts_inventory"
    __table_args__ = (UniqueConstraint("organization_id", "part_number", name="uq_parts_inventory_org_part_number"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True)
    part_number: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Array of {make, model} -- not normalized, per the plan's JSONB tradeoff.
    compatible_vehicles: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Mutated by side effects only (decrement/increment services) -- a direct PUT
    # is the one manual-adjustment exception, not the normal write path.
    qty_on_hand: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    reorder_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)


class PurchaseOrder(Base, OrgScopedMixin, AuditMixin):
    __tablename__ = "purchase_orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False)
    order_date: Mapped[date_] = mapped_column(Date, nullable=False)
    expected_delivery: Mapped[date_] = mapped_column(Date, nullable=False)
    actual_delivery: Mapped[date_ | None] = mapped_column(Date, nullable=True)
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        SAEnum(PurchaseOrderStatus, name="purchase_order_status"),
        default=PurchaseOrderStatus.pending,
        server_default=PurchaseOrderStatus.pending.value,
        nullable=False,
    )
    # Computed from line_items (sum of qty * unit_price) at creation time and
    # frozen -- not recalculated if line_items changes on a later PUT, matching
    # the write-time-freeze pattern used for other computed fields.
    total_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Array of {part_id, qty, unit_price} -- not a join table, per the plan's
    # JSONB tradeoff at this scale.
    line_items: Mapped[list] = mapped_column(JSONB, nullable=False)
