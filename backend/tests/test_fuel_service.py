from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.fuel import FuelLog
from app.models.organization import Organization
from app.schemas.fuel import FuelLogCreate
from app.services import fuel_service
from tests.conftest import make_user, make_vehicle


def test_transaction_rollback_on_commit_failure(db_session: Session, organization: Organization, monkeypatch: pytest.MonkeyPatch) -> None:
    """Forces the single create_fuel_log transaction to fail after the FuelLog
    insert and Vehicle.current_odometer update have both been staged, and
    asserts neither survives -- the two writes are genuinely one transaction."""
    admin = make_user(db_session, organization, role=UserRole.admin)
    vehicle = make_vehicle(db_session, organization, current_odometer=0)
    original_odometer = vehicle.current_odometer

    def _boom() -> None:
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(db_session, "commit", _boom)

    data = FuelLogCreate(
        vehicle_id=vehicle.id,
        date=date(2026, 6, 1),
        odometer_reading=1000,
        liters_filled="50.00",
        price_per_liter="20.00",
        total_cost="1000.00",
    )

    with pytest.raises(RuntimeError):
        fuel_service.create_fuel_log(db_session, organization.id, data, admin.id)

    # Undo the monkeypatch and roll back the session before using it again --
    # a session is not usable for further queries right after a failed commit.
    monkeypatch.undo()
    db_session.rollback()

    logs = db_session.execute(select(FuelLog).where(FuelLog.vehicle_id == vehicle.id)).scalars().all()
    assert logs == []

    db_session.refresh(vehicle)
    assert vehicle.current_odometer == original_odometer


def test_odometer_delta_guard_raises_before_any_write(db_session: Session, organization: Organization) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    vehicle = make_vehicle(db_session, organization, current_odometer=0)

    first = FuelLogCreate(
        vehicle_id=vehicle.id, date=date(2026, 6, 1), odometer_reading=1000,
        liters_filled="50.00", price_per_liter="20.00", total_cost="1000.00",
    )
    fuel_service.create_fuel_log(db_session, organization.id, first, admin.id)

    second = FuelLogCreate(
        vehicle_id=vehicle.id, date=date(2026, 6, 10), odometer_reading=1000,
        liters_filled="50.00", price_per_liter="20.00", total_cost="1000.00",
    )
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        fuel_service.create_fuel_log(db_session, organization.id, second, admin.id)
    assert exc_info.value.status_code == 400

    logs = db_session.execute(select(FuelLog).where(FuelLog.vehicle_id == vehicle.id)).scalars().all()
    assert len(logs) == 1  # only the first log persisted
