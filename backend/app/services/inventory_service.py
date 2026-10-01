import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory import PartsInventory
from app.schemas.inventory import PartsInventoryCreate, PartsInventoryUpdate

_DUPLICATE_PART_NUMBER_ERROR = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="A part with this part_number already exists"
)


def create_part(db: Session, org_id: uuid.UUID, data: PartsInventoryCreate, created_by: uuid.UUID) -> PartsInventory:
    # model_dump() recursively serializes compatible_vehicles (list[CompatibleVehicle])
    # into plain dicts, which is exactly what the JSONB column needs.
    part = PartsInventory(id=uuid.uuid4(), organization_id=org_id, created_by=created_by, **data.model_dump())
    db.add(part)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _DUPLICATE_PART_NUMBER_ERROR from exc
    db.refresh(part)
    return part


def get_part(db: Session, org_id: uuid.UUID, part_id: uuid.UUID) -> PartsInventory:
    part = db.execute(
        select(PartsInventory).where(
            PartsInventory.id == part_id,
            PartsInventory.organization_id == org_id,
            PartsInventory.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if part is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found")
    return part


def list_parts(
    db: Session,
    org_id: uuid.UUID,
    *,
    category: str | None = None,
    supplier_id: uuid.UUID | None = None,
    compatible_make: str | None = None,
    compatible_model: str | None = None,
) -> list[PartsInventory]:
    stmt = select(PartsInventory).where(PartsInventory.organization_id == org_id, PartsInventory.is_deleted.is_(False))
    if category is not None:
        stmt = stmt.where(PartsInventory.category == category)
    if supplier_id is not None:
        stmt = stmt.where(PartsInventory.supplier_id == supplier_id)
    parts = list(db.execute(stmt).scalars())

    # compatible_vehicles is a small JSONB array per part (not normalized, per
    # the plan's JSONB tradeoff at this scale) -- matching it is done in Python
    # over the already org/category/supplier-scoped result set rather than a
    # jsonb_array_elements EXISTS subquery, since that candidate set is small.
    if compatible_make is not None or compatible_model is not None:

        def _matches(part: PartsInventory) -> bool:
            for entry in part.compatible_vehicles or []:
                if compatible_make is not None and entry.get("make") != compatible_make:
                    continue
                if compatible_model is not None and entry.get("model") != compatible_model:
                    continue
                return True
            return False

        parts = [p for p in parts if _matches(p)]
    return parts


def list_low_stock(db: Session, org_id: uuid.UUID) -> list[PartsInventory]:
    """WHERE qty_on_hand < reorder_threshold -- a comparison, evaluated fresh on
    every call. No stored flag, no background job."""
    stmt = select(PartsInventory).where(
        PartsInventory.organization_id == org_id,
        PartsInventory.is_deleted.is_(False),
        PartsInventory.qty_on_hand < PartsInventory.reorder_threshold,
    )
    return list(db.execute(stmt).scalars())


def count_low_stock(db: Session, org_id: uuid.UUID) -> int:
    """len(list_low_stock(...)) as a SELECT COUNT(*)."""
    return db.execute(
        select(func.count(PartsInventory.id)).where(
            PartsInventory.organization_id == org_id,
            PartsInventory.is_deleted.is_(False),
            PartsInventory.qty_on_hand < PartsInventory.reorder_threshold,
        )
    ).scalar_one()


def update_part(
    db: Session, org_id: uuid.UUID, part_id: uuid.UUID, data: PartsInventoryUpdate, updated_by: uuid.UUID
) -> PartsInventory:
    part = get_part(db, org_id, part_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(part, field, value)
    part.updated_by = updated_by
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _DUPLICATE_PART_NUMBER_ERROR from exc
    db.refresh(part)
    return part


def decrement_stock_for_parts_used(db: Session, org_id: uuid.UUID, parts_used: list[dict]) -> list[dict]:
    """
    Called from maintenance_service.create_mechanic_report (Plan 03), inside
    that same transaction -- this function does NOT open or commit its own
    transaction. For each {part_id, qty} in parts_used: row-locks the part
    (SELECT ... FOR UPDATE) to avoid a race between concurrent decrements,
    decrements qty_on_hand (never letting it go negative), and flags low stock.
    Returns the list of low-stock alerts for the caller to include in its response.
    """
    alerts: list[dict] = []
    for item in parts_used:
        part_id = item["part_id"]
        qty = item["qty"]

        part = db.execute(
            select(PartsInventory)
            .where(
                PartsInventory.id == part_id,
                PartsInventory.organization_id == org_id,
                PartsInventory.is_deleted.is_(False),
            )
            .with_for_update()
        ).scalar_one_or_none()
        if part is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Part {part_id} not found")

        new_qty = part.qty_on_hand - qty
        if new_qty < 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Insufficient stock")
        part.qty_on_hand = new_qty

        if new_qty < part.reorder_threshold:
            alerts.append({"part_id": part_id, "low_stock_alert": True})

    return alerts


def increment_stock_for_line_items(db: Session, org_id: uuid.UUID, line_items: list[dict]) -> list[dict]:
    """
    Called from purchase_order_service.receive_purchase_order, inside that same
    transaction -- does not commit. For each {part_id, qty, unit_price} in
    line_items: increments qty_on_hand (row-locked, same as the decrement path).
    Returns [{part_id, new_qty}] for the receive response.
    """
    updates: list[dict] = []
    for item in line_items:
        part_id = item["part_id"]
        qty = item["qty"]

        part = db.execute(
            select(PartsInventory)
            .where(
                PartsInventory.id == part_id,
                PartsInventory.organization_id == org_id,
                PartsInventory.is_deleted.is_(False),
            )
            .with_for_update()
        ).scalar_one_or_none()
        if part is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Part {part_id} not found")

        part.qty_on_hand += qty
        updates.append({"part_id": part_id, "new_qty": part.qty_on_hand})

    return updates
