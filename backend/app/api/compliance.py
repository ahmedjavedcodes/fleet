import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_role
from app.models.enums import ServiceType, UserRole
from app.models.user import User
from app.schemas.compliance import (
    ComplianceRuleCreate,
    ComplianceRuleResponse,
    ComplianceRuleUpdate,
    FleetComplianceMatrixResponse,
    VehicleComplianceResponse,
)
from app.services import compliance_service

router = APIRouter(prefix="/api/v1/compliance", tags=["compliance"])

# ComplianceRule: admin full, fleet_manager full, driver none, mechanic read-only.
_WRITE_ROLES = (UserRole.admin, UserRole.fleet_manager)
_READ_ROLES = (UserRole.admin, UserRole.fleet_manager, UserRole.mechanic)


@router.post("/rules", response_model=ComplianceRuleResponse, status_code=status.HTTP_201_CREATED)
def create_rule(
    data: ComplianceRuleCreate,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> ComplianceRuleResponse:
    rule = compliance_service.create_rule(db, current_user.organization_id, data, current_user.id)
    return ComplianceRuleResponse.model_validate(rule)


@router.get("/rules", response_model=list[ComplianceRuleResponse])
def list_rules(
    make: str | None = None,
    model: str | None = None,
    service_type: ServiceType | None = None,
    current_user: User = Depends(require_role(*_READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[ComplianceRuleResponse]:
    rules = compliance_service.list_rules(
        db, current_user.organization_id, vehicle_make=make, vehicle_model=model, service_type=service_type
    )
    return [ComplianceRuleResponse.model_validate(r) for r in rules]


@router.put("/rules/{rule_id}", response_model=ComplianceRuleResponse)
def update_rule(
    rule_id: uuid.UUID,
    data: ComplianceRuleUpdate,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> ComplianceRuleResponse:
    rule = compliance_service.update_rule(db, current_user.organization_id, rule_id, data, current_user.id)
    return ComplianceRuleResponse.model_validate(rule)


@router.get("/status", response_model=FleetComplianceMatrixResponse)
def get_fleet_compliance_matrix(
    current_user: User = Depends(require_role(*_READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[VehicleComplianceResponse]:
    return compliance_service.get_fleet_compliance_matrix(db, current_user.organization_id)


@router.get("/status/{vehicle_id}", response_model=VehicleComplianceResponse)
def get_vehicle_compliance(
    vehicle_id: uuid.UUID,
    current_user: User = Depends(require_role(*_READ_ROLES)),
    db: Session = Depends(get_db),
) -> VehicleComplianceResponse:
    return compliance_service.get_vehicle_compliance(db, current_user.organization_id, vehicle_id)
