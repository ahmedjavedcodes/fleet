import uuid
from decimal import Decimal

from sqlalchemy import Enum as SAEnum, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import SupplierCategory
from app.models.mixins import AuditMixin, OrgScopedMixin


class Supplier(Base, OrgScopedMixin, AuditMixin):
    __tablename__ = "suppliers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    category: Mapped[SupplierCategory] = mapped_column(
        SAEnum(SupplierCategory, name="supplier_category"),
        default=SupplierCategory.other,
        server_default=SupplierCategory.other.value,
        nullable=False,
    )
    avg_lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Computed in Plan 02 (inventory/supplier services), not written here.
    reliability_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
