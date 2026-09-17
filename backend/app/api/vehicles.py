import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_role
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.vehicle import VehicleCreate, VehicleResponse, VehicleUpdate
from app.services import vehicle_service

router = APIRouter(prefix="/api/v1/vehicles", tags=["vehicles"])

# Vehicles, Drivers, Suppliers: admin/fleet_manager full, driver/mechanic read-only.
_WRITE_ROLES = (UserRole.admin, UserRole.fleet_manager)
_READ_ROLES = (UserRole.admin, UserRole.fleet_manager, UserRole.driver, UserRole.mechanic)


@router.post("", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED)
def create_vehicle(
    data: VehicleCreate,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    vehicle = vehicle_service.create_vehicle(db, current_user.organization_id, data, current_user.id)
    return VehicleResponse.model_validate(vehicle)


@router.get("", response_model=list[VehicleResponse])
def list_vehicles(
    current_user: User = Depends(require_role(*_READ_ROLES)),
    db: Session = Depends(get_db),
) -> list[VehicleResponse]:
    vehicles = vehicle_service.list_vehicles(db, current_user.organization_id)
    return [VehicleResponse.model_validate(v) for v in vehicles]


@router.get("/{vehicle_id}", response_model=VehicleResponse)
def get_vehicle(
    vehicle_id: uuid.UUID,
    current_user: User = Depends(require_role(*_READ_ROLES)),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    vehicle = vehicle_service.get_vehicle(db, current_user.organization_id, vehicle_id)
    return VehicleResponse.model_validate(vehicle)


@router.put("/{vehicle_id}", response_model=VehicleResponse)
def update_vehicle(
    vehicle_id: uuid.UUID,
    data: VehicleUpdate,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    vehicle = vehicle_service.update_vehicle(db, current_user.organization_id, vehicle_id, data, current_user.id)
    return VehicleResponse.model_validate(vehicle)


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vehicle(
    vehicle_id: uuid.UUID,
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
    db: Session = Depends(get_db),
) -> None:
    vehicle_service.delete_vehicle(db, current_user.organization_id, vehicle_id, current_user.id)
