import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_role
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.inventory import LowStockResponse, PartsInventoryCreate, PartsInventoryResponse, PartsInventoryUpdate
from app.services import inventory_service

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])

# PartsInventory: admin/fleet_manager full, driver none, mechanic read-only.
_WRITE_ROLES = (UserRole.admin, UserRole.fleet_manager)
_READ_ROLES = (UserRole.admin, UserRole.fleet_manager, UserRole.mechanic)


@router.post("", response_model=PartsInventoryResponse, status_code=status.HTTP_201_CREATED)
def create_part(
    data: PartsInventoryCreate,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> PartsInventoryResponse:
    part = inventory_service.create_part(db, current_user.organization_id, data, current_user.id)
    return PartsInventoryResponse.model_validate(part)


@router.get("", response_model=list[PartsInventoryResponse])
def list_parts(
    category: str | None = None,
    supplier_id: uuid.UUID | None = None,
    compatible_make: str | None = None,
    compatible_model: str | None = None,
    current_user: User = Depends(require_role(*_READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[PartsInventoryResponse]:
    parts = inventory_service.list_parts(
        db,
        current_user.organization_id,
        category=category,
        supplier_id=supplier_id,
        compatible_make=compatible_make,
        compatible_model=compatible_model,
    )
    return [PartsInventoryResponse.model_validate(p) for p in parts]


@router.get("/low-stock", response_model=list[LowStockResponse])
def list_low_stock(
    current_user: User = Depends(require_role(*_READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[LowStockResponse]:
    parts = inventory_service.list_low_stock(db, current_user.organization_id)
    return [
        LowStockResponse(
            **PartsInventoryResponse.model_validate(p).model_dump(), deficit=p.reorder_threshold - p.qty_on_hand
        )
        for p in parts
    ]


@router.put("/{part_id}", response_model=PartsInventoryResponse)
def update_part(
    part_id: uuid.UUID,
    data: PartsInventoryUpdate,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> PartsInventoryResponse:
    part = inventory_service.update_part(db, current_user.organization_id, part_id, data, current_user.id)
    return PartsInventoryResponse.model_validate(part)
