import uuid
from datetime import date as date_type
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import PurchaseOrderStatus
from app.models.inventory import PurchaseOrder
from app.schemas.inventory import (
    PurchaseOrderCreate,
    PurchaseOrderReceiveResponse,
    PurchaseOrderResponse,
    PurchaseOrderUpdate,
)
from app.services import inventory_service, supplier_service

_ALREADY_FINALIZED_ERROR = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="This purchase order has already been received or cancelled"
)


def _line_items_total(line_items: list) -> Decimal:
    return sum((item.qty * item.unit_price for item in line_items), start=Decimal("0"))


def create_purchase_order(db: Session, org_id: uuid.UUID, data: PurchaseOrderCreate, created_by: uuid.UUID) -> PurchaseOrder:
    # total_cost is computed from line_items at creation and frozen -- see
    # update_purchase_order for the one case it's recomputed (an edited
    # line_items list, before the order is received).
    order = PurchaseOrder(
        id=uuid.uuid4(),
        organization_id=org_id,
        created_by=created_by,
        supplier_id=data.supplier_id,
        order_date=data.order_date,
        expected_delivery=data.expected_delivery,
        line_items=[item.model_dump(mode="json") for item in data.line_items],
        total_cost=_line_items_total(data.line_items),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def get_purchase_order(db: Session, org_id: uuid.UUID, po_id: uuid.UUID) -> PurchaseOrder:
    order = db.execute(
        select(PurchaseOrder).where(
            PurchaseOrder.id == po_id,
            PurchaseOrder.organization_id == org_id,
            PurchaseOrder.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found")
    return order


def list_purchase_orders(
    db: Session,
    org_id: uuid.UUID,
    *,
    status: PurchaseOrderStatus | None = None,  # noqa: A002 -- shadows fastapi.status intentionally; not used below
    supplier_id: uuid.UUID | None = None,
    date_from: date_type | None = None,
    date_to: date_type | None = None,
) -> list[PurchaseOrder]:
    stmt = select(PurchaseOrder).where(PurchaseOrder.organization_id == org_id, PurchaseOrder.is_deleted.is_(False))
    if status is not None:
        stmt = stmt.where(PurchaseOrder.status == status)
    if supplier_id is not None:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    if date_from is not None:
        stmt = stmt.where(PurchaseOrder.order_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(PurchaseOrder.order_date <= date_to)
    stmt = stmt.order_by(PurchaseOrder.order_date.desc())
    return list(db.execute(stmt).scalars())


def update_purchase_order(
    db: Session, org_id: uuid.UUID, po_id: uuid.UUID, data: PurchaseOrderUpdate, updated_by: uuid.UUID
) -> PurchaseOrder:
    """Rejects edits if status == 'received' -- a received order is immutable,
    matching the append-only spirit applied elsewhere to finalized records.
    Receiving itself only ever happens through receive_purchase_order, never
    through this generic update (status='received' is rejected as a payload
    value here, since that transition must run the stock/reliability side effects)."""
    order = get_purchase_order(db, org_id, po_id)
    if order.status == PurchaseOrderStatus.received:
        raise _ALREADY_FINALIZED_ERROR

    updates = data.model_dump(exclude_unset=True)
    if updates.get("status") == PurchaseOrderStatus.received:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use PATCH /purchase-orders/{id}/receive to mark an order received",
        )

    if "line_items" in updates:
        line_items = data.line_items
        updates["line_items"] = [item.model_dump(mode="json") for item in line_items]
        updates["total_cost"] = _line_items_total(line_items)

    for field, value in updates.items():
        setattr(order, field, value)
    order.updated_by = updated_by
    db.commit()
    db.refresh(order)
    return order


def receive_purchase_order(db: Session, org_id: uuid.UUID, po_id: uuid.UUID, received_by: uuid.UUID) -> PurchaseOrderReceiveResponse:
    """
    Single transaction:
      1. Fetch PO (org-scoped). 409 if status is already 'received' or 'cancelled'.
      2. Set actual_delivery = today, status = 'received'.
      3. Increment stock for every line item.
      4. Recalculate the supplier's reliability_score and avg_lead_time_days.
      5. Commit. Any failure rolls all of the above back together.
    """
    order = get_purchase_order(db, org_id, po_id)
    if order.status in (PurchaseOrderStatus.received, PurchaseOrderStatus.cancelled):
        raise _ALREADY_FINALIZED_ERROR

    order.actual_delivery = datetime.now(timezone.utc).date()
    order.status = PurchaseOrderStatus.received
    order.updated_by = received_by

    stock_updates = inventory_service.increment_stock_for_line_items(db, org_id, order.line_items)

    # The Session is autoflush=False (see app/core/database.py), so without an
    # explicit flush here, _recalculate_reliability_score's SELECT would not
    # see this order's own pending status/actual_delivery change, excluding
    # the order currently being received from its own reliability computation.
    db.flush()
    supplier_service._recalculate_reliability_score(db, org_id, order.supplier_id)
    supplier_service._recalculate_avg_lead_time(db, org_id, order.supplier_id)

    db.commit()
    db.refresh(order)
    return PurchaseOrderReceiveResponse(order=PurchaseOrderResponse.model_validate(order), stock_updates=stock_updates)
