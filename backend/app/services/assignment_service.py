import uuid
from datetime import date as date_type

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.assignment import VehicleAssignment
from app.models.driver import Driver
from app.models.enums import DriverStatus, VehicleStatus
from app.models.vehicle import Vehicle
from app.schemas.assignment import DriverAssignmentHistoryResponse, VehicleAssignRequest, VehicleAssignmentResponse, VehicleReleaseRequest

_VEHICLE_ALREADY_ASSIGNED = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="Vehicle already has an active assignment"
)
_DRIVER_ALREADY_ASSIGNED = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="Driver already has an active assignment"
)
_NO_ACTIVE_ASSIGNMENT = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="No active assignment found for this vehicle"
)


def _get_active_vehicle_or_404(db: Session, org_id: uuid.UUID, vehicle_id: uuid.UUID) -> Vehicle:
    vehicle = db.execute(
        select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.organization_id == org_id, Vehicle.is_deleted.is_(False))
    ).scalar_one_or_none()
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    if vehicle.status != VehicleStatus.active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vehicle is not active")
    return vehicle


def _get_active_driver_or_404(db: Session, org_id: uuid.UUID, driver_id: uuid.UUID) -> Driver:
    driver = db.execute(
        select(Driver).where(Driver.id == driver_id, Driver.organization_id == org_id, Driver.is_deleted.is_(False))
    ).scalar_one_or_none()
    if driver is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found")
    if driver.status != DriverStatus.active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Driver is not active")
    return driver


def _get_active_assignment_for_vehicle(db: Session, org_id: uuid.UUID, vehicle_id: uuid.UUID) -> VehicleAssignment | None:
    return db.execute(
        select(VehicleAssignment).where(
            VehicleAssignment.vehicle_id == vehicle_id,
            VehicleAssignment.organization_id == org_id,
            VehicleAssignment.is_deleted.is_(False),
            VehicleAssignment.released_at.is_(None),
        )
    ).scalar_one_or_none()


def _get_active_assignment_for_driver(db: Session, org_id: uuid.UUID, driver_id: uuid.UUID) -> VehicleAssignment | None:
    return db.execute(
        select(VehicleAssignment).where(
            VehicleAssignment.driver_id == driver_id,
            VehicleAssignment.organization_id == org_id,
            VehicleAssignment.is_deleted.is_(False),
            VehicleAssignment.released_at.is_(None),
        )
    ).scalar_one_or_none()


def assign_vehicle(
    db: Session, org_id: uuid.UUID, vehicle_id: uuid.UUID, data: VehicleAssignRequest, created_by: uuid.UUID
) -> VehicleAssignment:
    _get_active_vehicle_or_404(db, org_id, vehicle_id)
    _get_active_driver_or_404(db, org_id, data.driver_id)

    if _get_active_assignment_for_vehicle(db, org_id, vehicle_id) is not None:
        raise _VEHICLE_ALREADY_ASSIGNED
    if _get_active_assignment_for_driver(db, org_id, data.driver_id) is not None:
        raise _DRIVER_ALREADY_ASSIGNED

    assignment = VehicleAssignment(
        id=uuid.uuid4(),
        organization_id=org_id,
        created_by=created_by,
        vehicle_id=vehicle_id,
        driver_id=data.driver_id,
        assigned_at=data.assigned_at,
        start_odometer=data.start_odometer,
        take_condition=data.take_condition,
        take_notes=data.take_notes,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment


def release_vehicle(
    db: Session, org_id: uuid.UUID, vehicle_id: uuid.UUID, data: VehicleReleaseRequest, updated_by: uuid.UUID
) -> VehicleAssignment:
    assignment = _get_active_assignment_for_vehicle(db, org_id, vehicle_id)
    if assignment is None:
        raise _NO_ACTIVE_ASSIGNMENT

    if data.released_at < assignment.assigned_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="released_at cannot be before assigned_at")
    if data.end_odometer < assignment.start_odometer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="end_odometer cannot be less than start_odometer"
        )

    assignment.released_at = data.released_at
    assignment.end_odometer = data.end_odometer
    assignment.leave_condition = data.leave_condition
    assignment.leave_notes = data.leave_notes
    assignment.updated_by = updated_by

    # Odometer currency: only push forward, mirroring the same "never regress
    # current_odometer" principle used by fuel/trip logging -- a handover
    # reading behind the vehicle's already-recorded odometer is not a source
    # of truth for it.
    vehicle = db.execute(select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.organization_id == org_id)).scalar_one()
    if data.end_odometer > vehicle.current_odometer:
        vehicle.current_odometer = data.end_odometer

    db.commit()
    db.refresh(assignment)
    return assignment


def get_driver_assignment_history(db: Session, org_id: uuid.UUID, driver_id: uuid.UUID) -> DriverAssignmentHistoryResponse:
    assignments = list(
        db.execute(
            select(VehicleAssignment)
            .where(
                VehicleAssignment.driver_id == driver_id,
                VehicleAssignment.organization_id == org_id,
                VehicleAssignment.is_deleted.is_(False),
            )
            .order_by(VehicleAssignment.assigned_at.desc())
        ).scalars()
    )
    current = next((a for a in assignments if a.released_at is None), None)
    total_vehicles_driven = len({a.vehicle_id for a in assignments})

    return DriverAssignmentHistoryResponse(
        driver_id=driver_id,
        current_assignment=VehicleAssignmentResponse.model_validate(current) if current is not None else None,
        total_vehicles_driven=total_vehicles_driven,
        history=[VehicleAssignmentResponse.model_validate(a) for a in assignments],
    )


def get_vehicle_assignment_history(
    db: Session, org_id: uuid.UUID, vehicle_id: uuid.UUID, target_date: date_type | None = None
) -> list[VehicleAssignment]:
    stmt = select(VehicleAssignment).where(
        VehicleAssignment.vehicle_id == vehicle_id,
        VehicleAssignment.organization_id == org_id,
        VehicleAssignment.is_deleted.is_(False),
    )
    if target_date is not None:
        stmt = stmt.where(
            VehicleAssignment.assigned_at <= target_date,
            or_(VehicleAssignment.released_at.is_(None), VehicleAssignment.released_at >= target_date),
        )
    stmt = stmt.order_by(VehicleAssignment.assigned_at.desc())
    return list(db.execute(stmt).scalars())
