import uuid
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import PurchaseOrderStatus, SupplierCategory
from app.models.inventory import PurchaseOrder
from app.models.supplier import Supplier
from app.schemas.supplier import SupplierCreate, SupplierUpdate


def create_supplier(db: Session, org_id: uuid.UUID, data: SupplierCreate, created_by: uuid.UUID) -> Supplier:
    supplier = Supplier(id=uuid.uuid4(), organization_id=org_id, created_by=created_by, **data.model_dump())
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return supplier


def get_supplier(db: Session, org_id: uuid.UUID, supplier_id: uuid.UUID) -> Supplier:
    supplier = db.execute(
        select(Supplier).where(
            Supplier.id == supplier_id,
            Supplier.organization_id == org_id,
            Supplier.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if supplier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    return supplier


def list_suppliers(
    db: Session, org_id: uuid.UUID, sort_by_reliability: bool = False, category: SupplierCategory | None = None
) -> list[Supplier]:
    stmt = select(Supplier).where(Supplier.organization_id == org_id, Supplier.is_deleted.is_(False))
    if category is not None:
        stmt = stmt.where(Supplier.category == category)
    if sort_by_reliability:
        # NULLS LAST so suppliers with no scored history yet sort after scored ones.
        stmt = stmt.order_by(Supplier.reliability_score.desc().nulls_last())
    return list(db.execute(stmt).scalars())


def update_supplier(
    db: Session, org_id: uuid.UUID, supplier_id: uuid.UUID, data: SupplierUpdate, updated_by: uuid.UUID
) -> Supplier:
    supplier = get_supplier(db, org_id, supplier_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(supplier, field, value)
    supplier.updated_by = updated_by
    db.commit()
    db.refresh(supplier)
    return supplier


def _recalculate_reliability_score(db: Session, org_id: uuid.UUID, supplier_id: uuid.UUID) -> Decimal | None:
    """
    reliability_score = count(received orders where actual_delivery <= expected_delivery)
                       / count(received orders)

    Called only from purchase_order_service.receive_purchase_order, inside that
    same transaction -- this function does not commit. It sets
    Supplier.reliability_score on the ORM object and returns the new value;
    the caller's own db.commit() persists it alongside the stock update.
    """
    total_received, on_time = db.execute(
        select(
            func.count(PurchaseOrder.id),
            func.count(PurchaseOrder.id).filter(PurchaseOrder.actual_delivery <= PurchaseOrder.expected_delivery),
        ).where(
            PurchaseOrder.organization_id == org_id,
            PurchaseOrder.supplier_id == supplier_id,
            PurchaseOrder.is_deleted.is_(False),
            PurchaseOrder.status == PurchaseOrderStatus.received,
        )
    ).one()

    score: Decimal | None = None
    if total_received > 0:
        score = (Decimal(on_time) / Decimal(total_received)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    supplier = get_supplier(db, org_id, supplier_id)
    supplier.reliability_score = score
    return score
