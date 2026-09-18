import uuid
from datetime import date

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_role
from app.models.enums import PurchaseOrderStatus, UserRole
from app.models.user import User
from app.schemas.inventory import (
    PurchaseOrderCreate,
    PurchaseOrderReceiveResponse,
    PurchaseOrderResponse,
    PurchaseOrderUpdate,
)
from app.services import purchase_order_service

# Hyphenated to match this project's route convention (/driver-reports,
# /purchase-orders in the plan/spec), not the underscored form.
router = APIRouter(prefix="/api/v1/purchase-orders", tags=["purchase-orders"])

# PurchaseOrder: admin/fleet_manager full, driver none, mechanic read-only.
_WRITE_ROLES = (UserRole.admin, UserRole.fleet_manager)
_READ_ROLES = (UserRole.admin, UserRole.fleet_manager, UserRole.mechanic)


@router.post("", response_model=PurchaseOrderResponse, status_code=status.HTTP_201_CREATED)
def create_purchase_order(
    data: PurchaseOrderCreate,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> PurchaseOrderResponse:
    order = purchase_order_service.create_purchase_order(db, current_user.organization_id, data, current_user.id)
    return PurchaseOrderResponse.model_validate(order)


@router.get("", response_model=list[PurchaseOrderResponse])
def list_purchase_orders(
    status: PurchaseOrderStatus | None = None,
    supplier_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    current_user: User = Depends(require_role(*_READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[PurchaseOrderResponse]:
    orders = purchase_order_service.list_purchase_orders(
        db,
        current_user.organization_id,
        status=status,
        supplier_id=supplier_id,
        date_from=date_from,
        date_to=date_to,
    )
    return [PurchaseOrderResponse.model_validate(o) for o in orders]


@router.put("/{po_id}", response_model=PurchaseOrderResponse)
def update_purchase_order(
    po_id: uuid.UUID,
    data: PurchaseOrderUpdate,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> PurchaseOrderResponse:
    order = purchase_order_service.update_purchase_order(db, current_user.organization_id, po_id, data, current_user.id)
    return PurchaseOrderResponse.model_validate(order)


@router.patch("/{po_id}/receive", response_model=PurchaseOrderReceiveResponse)
def receive_purchase_order(
    po_id: uuid.UUID,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> PurchaseOrderReceiveResponse:
    return purchase_order_service.receive_purchase_order(db, current_user.organization_id, po_id, current_user.id)
