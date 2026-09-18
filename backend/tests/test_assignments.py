import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import DriverStatus, UserRole, VehicleStatus
from app.models.organization import Organization
from app.models.vehicle import Vehicle
from app.services import assignment_service
from tests.conftest import auth_headers, make_assignment, make_driver, make_user, make_vehicle

T1 = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 6, 1, 17, 0, tzinfo=timezone.utc)  # T1 + 8 hours


@pytest.fixture()
def admin(db_session: Session, organization: Organization):
    return make_user(db_session, organization, role=UserRole.admin)


@pytest.fixture()
def driver_setup(db_session: Session, organization: Organization):
    driver_user = make_user(db_session, organization, role=UserRole.driver)
    driver_profile = make_driver(db_session, organization, user=driver_user)
    return driver_user, driver_profile


def _assign_payload(driver_id, **overrides) -> dict:
    payload = {
        "driver_id": str(driver_id),
        "assigned_at": T1.isoformat(),
        "start_odometer": 1000,
        "take_condition": "good",
    }
    payload.update(overrides)
    return payload


def _release_payload(**overrides) -> dict:
    payload = {
        "released_at": T2.isoformat(),
        "end_odometer": 1100,
        "leave_condition": "fair",
    }
    payload.update(overrides)
    return payload


# --- Assign / release workflow -----------------------------------------------------


def test_assign_and_release_workflow_success(client: TestClient, db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization, current_odometer=500)
    driver = make_driver(db_session, organization)

    assign_response = client.post(
        f"/api/v1/vehicles/{vehicle.id}/assign", json=_assign_payload(driver.id), headers=auth_headers(admin)
    )
    assert assign_response.status_code == 201
    body = assign_response.json()
    assert body["vehicle_id"] == str(vehicle.id)
    assert body["driver_id"] == str(driver.id)
    assert body["released_at"] is None
    assert body["duration_hours"] is None

    release_response = client.post(
        f"/api/v1/vehicles/{vehicle.id}/release", json=_release_payload(), headers=auth_headers(admin)
    )
    assert release_response.status_code == 200
    released = release_response.json()
    assert released["released_at"] is not None
    assert released["end_odometer"] == 1100
    assert released["leave_condition"] == "fair"
    assert released["duration_hours"] == 8.0


def test_release_odometer_sync_updates_vehicle_when_end_odometer_greater(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    vehicle = make_vehicle(db_session, organization, current_odometer=500)
    driver = make_driver(db_session, organization)
    client.post(f"/api/v1/vehicles/{vehicle.id}/assign", json=_assign_payload(driver.id), headers=auth_headers(admin))

    client.post(f"/api/v1/vehicles/{vehicle.id}/release", json=_release_payload(end_odometer=9000), headers=auth_headers(admin))

    db_session.expire_all()
    refreshed = db_session.get(Vehicle, vehicle.id)
    assert refreshed.current_odometer == 9000


def test_release_does_not_regress_vehicle_odometer_when_end_odometer_lower(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    """Vehicle.current_odometer is already ahead (e.g. updated by a later fuel
    log) of this assignment's end_odometer -- release must never move it backwards."""
    vehicle = make_vehicle(db_session, organization, current_odometer=50000)
    driver = make_driver(db_session, organization)
    client.post(
        f"/api/v1/vehicles/{vehicle.id}/assign",
        json=_assign_payload(driver.id, start_odometer=1000),
        headers=auth_headers(admin),
    )

    client.post(f"/api/v1/vehicles/{vehicle.id}/release", json=_release_payload(end_odometer=1100), headers=auth_headers(admin))

    db_session.expire_all()
    refreshed = db_session.get(Vehicle, vehicle.id)
    assert refreshed.current_odometer == 50000


def test_assign_conflict_when_vehicle_already_assigned(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    vehicle = make_vehicle(db_session, organization)
    driver1 = make_driver(db_session, organization)
    driver2 = make_driver(db_session, organization)
    client.post(f"/api/v1/vehicles/{vehicle.id}/assign", json=_assign_payload(driver1.id), headers=auth_headers(admin))

    response = client.post(f"/api/v1/vehicles/{vehicle.id}/assign", json=_assign_payload(driver2.id), headers=auth_headers(admin))
    assert response.status_code == 409


def test_assign_conflict_when_driver_already_assigned(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    vehicle1 = make_vehicle(db_session, organization)
    vehicle2 = make_vehicle(db_session, organization)
    driver = make_driver(db_session, organization)
    client.post(f"/api/v1/vehicles/{vehicle1.id}/assign", json=_assign_payload(driver.id), headers=auth_headers(admin))

    response = client.post(f"/api/v1/vehicles/{vehicle2.id}/assign", json=_assign_payload(driver.id), headers=auth_headers(admin))
    assert response.status_code == 409


def test_assign_allowed_again_after_release(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    vehicle = make_vehicle(db_session, organization)
    driver1 = make_driver(db_session, organization)
    driver2 = make_driver(db_session, organization)
    client.post(f"/api/v1/vehicles/{vehicle.id}/assign", json=_assign_payload(driver1.id), headers=auth_headers(admin))
    client.post(f"/api/v1/vehicles/{vehicle.id}/release", json=_release_payload(), headers=auth_headers(admin))

    response = client.post(f"/api/v1/vehicles/{vehicle.id}/assign", json=_assign_payload(driver2.id), headers=auth_headers(admin))
    assert response.status_code == 201


def test_assign_rejects_inactive_vehicle(client: TestClient, db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization, status=VehicleStatus.maintenance)
    driver = make_driver(db_session, organization)
    response = client.post(f"/api/v1/vehicles/{vehicle.id}/assign", json=_assign_payload(driver.id), headers=auth_headers(admin))
    assert response.status_code == 400


def test_assign_rejects_inactive_driver(client: TestClient, db_session: Session, organization: Organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization)
    driver = make_driver(db_session, organization, status=DriverStatus.suspended)
    response = client.post(f"/api/v1/vehicles/{vehicle.id}/assign", json=_assign_payload(driver.id), headers=auth_headers(admin))
    assert response.status_code == 400


def test_release_rejects_end_odometer_less_than_start_odometer(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    vehicle = make_vehicle(db_session, organization)
    driver = make_driver(db_session, organization)
    client.post(
        f"/api/v1/vehicles/{vehicle.id}/assign",
        json=_assign_payload(driver.id, start_odometer=5000),
        headers=auth_headers(admin),
    )

    response = client.post(
        f"/api/v1/vehicles/{vehicle.id}/release", json=_release_payload(end_odometer=100), headers=auth_headers(admin)
    )
    assert response.status_code == 400


def test_release_rejects_released_at_before_assigned_at(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    vehicle = make_vehicle(db_session, organization)
    driver = make_driver(db_session, organization)
    client.post(f"/api/v1/vehicles/{vehicle.id}/assign", json=_assign_payload(driver.id), headers=auth_headers(admin))

    earlier = (T1 - timedelta(hours=1)).isoformat()
    response = client.post(
        f"/api/v1/vehicles/{vehicle.id}/release", json=_release_payload(released_at=earlier), headers=auth_headers(admin)
    )
    assert response.status_code == 400


def test_release_no_active_assignment_returns_404(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    vehicle = make_vehicle(db_session, organization)
    response = client.post(f"/api/v1/vehicles/{vehicle.id}/release", json=_release_payload(), headers=auth_headers(admin))
    assert response.status_code == 404


# --- Point-in-time vehicle history --------------------------------------------------


def test_vehicle_assignment_history_point_in_time_query(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    vehicle = make_vehicle(db_session, organization)
    driver1 = make_driver(db_session, organization)
    driver2 = make_driver(db_session, organization)

    old = make_assignment(
        db_session, organization, vehicle, driver1,
        assigned_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        released_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        end_odometer=2000,
        leave_condition="good",
    )
    current = make_assignment(
        db_session, organization, vehicle, driver2,
        assigned_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        start_odometer=2000,
    )

    response = client.get(
        f"/api/v1/vehicles/{vehicle.id}/assignments", params={"target_date": "2026-01-15"}, headers=auth_headers(admin)
    )
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()]
    assert str(old.id) in ids
    assert str(current.id) not in ids

    response2 = client.get(
        f"/api/v1/vehicles/{vehicle.id}/assignments", params={"target_date": "2026-04-01"}, headers=auth_headers(admin)
    )
    ids2 = [item["id"] for item in response2.json()]
    assert str(current.id) in ids2
    assert str(old.id) not in ids2


def test_vehicle_assignment_history_no_target_date_returns_all(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    vehicle = make_vehicle(db_session, organization)
    driver = make_driver(db_session, organization)
    make_assignment(
        db_session, organization, vehicle, driver,
        assigned_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        released_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        end_odometer=2000,
        leave_condition="good",
    )
    response = client.get(f"/api/v1/vehicles/{vehicle.id}/assignments", headers=auth_headers(admin))
    assert response.status_code == 200
    assert len(response.json()) == 1


# --- Driver history & unique vehicle count ------------------------------------------


def test_driver_history_and_unique_vehicle_count(client: TestClient, db_session: Session, organization: Organization, admin) -> None:
    driver = make_driver(db_session, organization)
    vehicle1 = make_vehicle(db_session, organization)
    vehicle2 = make_vehicle(db_session, organization)

    make_assignment(
        db_session, organization, vehicle1, driver,
        assigned_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        released_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        end_odometer=2000,
        leave_condition="good",
    )
    make_assignment(db_session, organization, vehicle2, driver, assigned_at=datetime(2026, 3, 1, tzinfo=timezone.utc))

    response = client.get(f"/api/v1/drivers/{driver.id}/assignments", headers=auth_headers(admin))
    assert response.status_code == 200
    body = response.json()
    assert body["driver_id"] == str(driver.id)
    assert body["total_vehicles_driven"] == 2
    assert len(body["history"]) == 2
    assert body["current_assignment"]["vehicle_id"] == str(vehicle2.id)


def test_driver_history_current_assignment_null_when_none_active(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    driver = make_driver(db_session, organization)
    response = client.get(f"/api/v1/drivers/{driver.id}/assignments", headers=auth_headers(admin))
    assert response.status_code == 200
    body = response.json()
    assert body["current_assignment"] is None
    assert body["total_vehicles_driven"] == 0


# --- RBAC ----------------------------------------------------------------------------


@pytest.mark.parametrize("role", [UserRole.driver, UserRole.mechanic])
def test_assign_and_release_forbidden_for_driver_and_mechanic(
    client: TestClient, db_session: Session, organization: Organization, role: UserRole
) -> None:
    vehicle = make_vehicle(db_session, organization)
    driver = make_driver(db_session, organization)
    user = make_user(db_session, organization, role=role)

    assign_response = client.post(f"/api/v1/vehicles/{vehicle.id}/assign", json=_assign_payload(driver.id), headers=auth_headers(user))
    assert assign_response.status_code == 403

    release_response = client.post(f"/api/v1/vehicles/{vehicle.id}/release", json=_release_payload(), headers=auth_headers(user))
    assert release_response.status_code == 403


@pytest.mark.parametrize("role", [UserRole.admin, UserRole.fleet_manager])
def test_assign_allowed_for_admin_and_fleet_manager(
    client: TestClient, db_session: Session, organization: Organization, role: UserRole
) -> None:
    vehicle = make_vehicle(db_session, organization)
    driver = make_driver(db_session, organization)
    user = make_user(db_session, organization, role=role)
    response = client.post(f"/api/v1/vehicles/{vehicle.id}/assign", json=_assign_payload(driver.id), headers=auth_headers(user))
    assert response.status_code == 201


def test_driver_can_view_own_assignment_history_not_anothers(
    client: TestClient, db_session: Session, organization: Organization, driver_setup
) -> None:
    driver_user, driver_profile = driver_setup
    other_driver = make_driver(db_session, organization)

    own = client.get(f"/api/v1/drivers/{driver_profile.id}/assignments", headers=auth_headers(driver_user))
    other = client.get(f"/api/v1/drivers/{other_driver.id}/assignments", headers=auth_headers(driver_user))
    assert own.status_code == 200
    assert other.status_code == 403


def test_mechanic_forbidden_on_driver_assignment_history(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    driver = make_driver(db_session, organization)
    mechanic = make_user(db_session, organization, role=UserRole.mechanic)
    response = client.get(f"/api/v1/drivers/{driver.id}/assignments", headers=auth_headers(mechanic))
    assert response.status_code == 403


@pytest.mark.parametrize("role", [UserRole.admin, UserRole.fleet_manager, UserRole.driver])
def test_vehicle_assignment_history_open_to_admin_manager_driver(
    client: TestClient, db_session: Session, organization: Organization, role: UserRole
) -> None:
    vehicle = make_vehicle(db_session, organization)
    user = make_user(db_session, organization, role=role)
    response = client.get(f"/api/v1/vehicles/{vehicle.id}/assignments", headers=auth_headers(user))
    assert response.status_code == 200


def test_mechanic_forbidden_on_vehicle_assignment_history(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    vehicle = make_vehicle(db_session, organization)
    mechanic = make_user(db_session, organization, role=UserRole.mechanic)
    response = client.get(f"/api/v1/vehicles/{vehicle.id}/assignments", headers=auth_headers(mechanic))
    assert response.status_code == 403


# --- Multi-tenant scoping -------------------------------------------------------------


def test_org_scoping_assign_rejects_cross_org_vehicle(
    client: TestClient, db_session: Session, organization: Organization, admin
) -> None:
    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()
    other_vehicle = make_vehicle(db_session, other_org)
    driver = make_driver(db_session, organization)

    response = client.post(
        f"/api/v1/vehicles/{other_vehicle.id}/assign", json=_assign_payload(driver.id), headers=auth_headers(admin)
    )
    assert response.status_code == 404


def test_org_scoping_vehicle_assignment_history_excludes_other_org(db_session: Session, organization: Organization) -> None:
    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()

    vehicle = make_vehicle(db_session, organization)
    driver = make_driver(db_session, organization)
    make_assignment(db_session, organization, vehicle, driver)

    history = assignment_service.get_vehicle_assignment_history(db_session, other_org.id, vehicle.id)
    assert history == []


def test_org_scoping_driver_history_excludes_other_org(db_session: Session, organization: Organization) -> None:
    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()

    vehicle = make_vehicle(db_session, organization)
    driver = make_driver(db_session, organization)
    make_assignment(db_session, organization, vehicle, driver)

    result = assignment_service.get_driver_assignment_history(db_session, other_org.id, driver.id)
    assert result.total_vehicles_driven == 0
    assert result.history == []
