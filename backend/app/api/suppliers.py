import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_role
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.supplier import SupplierCreate, SupplierResponse, SupplierUpdate
from app.services import supplier_service

router = APIRouter(prefix="/api/v1/suppliers", tags=["suppliers"])

_WRITE_ROLES = (UserRole.admin, UserRole.fleet_manager)
_READ_ROLES = (UserRole.admin, UserRole.fleet_manager, UserRole.driver, UserRole.mechanic)


@router.post("", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED)
def create_supplier(
    data: SupplierCreate,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> SupplierResponse:
    supplier = supplier_service.create_supplier(db, current_user.organization_id, data, current_user.id)
    return SupplierResponse.model_validate(supplier)


@router.get("", response_model=list[SupplierResponse])
def list_suppliers(
    sort: str | None = Query(default=None, description="Set to 'reliability_score' to sort by it"),
    current_user: User = Depends(require_role(*_READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[SupplierResponse]:
    suppliers = supplier_service.list_suppliers(
        db, current_user.organization_id, sort_by_reliability=(sort == "reliability_score")
    )
    return [SupplierResponse.model_validate(s) for s in suppliers]


@router.put("/{supplier_id}", response_model=SupplierResponse)
def update_supplier(
    supplier_id: uuid.UUID,
    data: SupplierUpdate,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> SupplierResponse:
    supplier = supplier_service.update_supplier(db, current_user.organization_id, supplier_id, data, current_user.id)
    return SupplierResponse.model_validate(supplier)
