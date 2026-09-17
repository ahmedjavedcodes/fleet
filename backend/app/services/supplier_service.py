import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

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


def list_suppliers(db: Session, org_id: uuid.UUID, sort_by_reliability: bool = False) -> list[Supplier]:
    stmt = select(Supplier).where(Supplier.organization_id == org_id, Supplier.is_deleted.is_(False))
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
