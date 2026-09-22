import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.driver import Driver
from app.models.enums import UserRole
from app.models.organization import Organization
from tests.conftest import auth_headers, make_user

ALL_ROLES = [UserRole.admin, UserRole.fleet_manager, UserRole.driver, UserRole.mechanic]
WRITE_ROLES = {UserRole.admin, UserRole.fleet_manager}


@pytest.fixture()
def vehicle_payload() -> dict:
    return {
        "plate_number": f"PLT-{uuid.uuid4().hex[:6]}",
        "make": "Toyota",
        "model": "Hilux",
        "year": 2020,
        "vin": uuid.uuid4().hex[:17],
        "fuel_type": "diesel",
    }


@pytest.mark.parametrize("role", ALL_ROLES)
def test_vehicle_list_and_get_allowed_for_all_roles(
    client: TestClient, db_session: Session, organization: Organization, vehicle_payload: dict, role: UserRole
) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    created = client.post("/api/v1/vehicles", json=vehicle_payload, headers=auth_headers(admin))
    assert created.status_code == 201
    vehicle_id = created.json()["id"]

    user = make_user(db_session, organization, role=role)
    list_resp = client.get("/api/v1/vehicles", headers=auth_headers(user))
    get_resp = client.get(f"/api/v1/vehicles/{vehicle_id}", headers=auth_headers(user))
    assert list_resp.status_code == 200
    assert get_resp.status_code == 200


@pytest.mark.parametrize("role", [UserRole.driver, UserRole.mechanic])
def test_vehicle_crud_role_gating_write_forbidden(
    client: TestClient, db_session: Session, organization: Organization, vehicle_payload: dict, role: UserRole
) -> None:
    user = make_user(db_session, organization, role=role)
    create_resp = client.post("/api/v1/vehicles", json=vehicle_payload, headers=auth_headers(user))
    assert create_resp.status_code == 403

    admin = make_user(db_session, organization, role=UserRole.admin)
    seeded = client.post("/api/v1/vehicles", json=vehicle_payload, headers=auth_headers(admin)).json()

    update_resp = client.put(f"/api/v1/vehicles/{seeded['id']}", json={"year": 2021}, headers=auth_headers(user))
    delete_resp = client.delete(f"/api/v1/vehicles/{seeded['id']}", headers=auth_headers(user))
    assert update_resp.status_code == 403
    assert delete_resp.status_code == 403


@pytest.mark.parametrize("role", [UserRole.admin, UserRole.fleet_manager])
def test_vehicle_crud_role_gating_write_allowed(
    client: TestClient, db_session: Session, organization: Organization, vehicle_payload: dict, role: UserRole
) -> None:
    user = make_user(db_session, organization, role=role)
    create_resp = client.post("/api/v1/vehicles", json=vehicle_payload, headers=auth_headers(user))
    assert create_resp.status_code == 201
    vehicle_id = create_resp.json()["id"]

    update_resp = client.put(f"/api/v1/vehicles/{vehicle_id}", json={"year": 2022}, headers=auth_headers(user))
    assert update_resp.status_code == 200
    assert update_resp.json()["year"] == 2022

    delete_resp = client.delete(f"/api/v1/vehicles/{vehicle_id}", headers=auth_headers(user))
    assert delete_resp.status_code == 204

    get_resp = client.get(f"/api/v1/vehicles/{vehicle_id}", headers=auth_headers(user))
    assert get_resp.status_code == 404  # soft-deleted, excluded from normal queries


def test_require_role_rejects_wrong_role_with_403_not_401(
    client: TestClient, db_session: Session, organization: Organization, vehicle_payload: dict
) -> None:
    driver_user = make_user(db_session, organization, role=UserRole.driver)
    response = client.post("/api/v1/vehicles", json=vehicle_payload, headers=auth_headers(driver_user))
    assert response.status_code == 403


def test_missing_or_invalid_token_is_401_before_role_check(client: TestClient, vehicle_payload: dict) -> None:
    response = client.post("/api/v1/vehicles", json=vehicle_payload, headers={"Authorization": "Bearer garbage-token"})
    assert response.status_code == 401


def test_driver_profile_lookup_returns_none_when_unlinked(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    driver_user = make_user(db_session, organization, role=UserRole.driver)
    response = client.get("/api/v1/auth/me", headers=auth_headers(driver_user))
    assert response.status_code == 200
    assert response.json()["driver_profile"] is None


def test_driver_profile_lookup_returns_linked_driver(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    driver_user = make_user(db_session, organization, role=UserRole.driver)
    driver = Driver(
        id=uuid.uuid4(),
        organization_id=organization.id,
        user_id=driver_user.id,
        full_name="Linked Driver",
        license_number="LIC-1",
        license_expiry=date(2030, 1, 1),
        phone="555-0100",
    )
    db_session.add(driver)
    db_session.commit()

    response = client.get("/api/v1/auth/me", headers=auth_headers(driver_user))
    assert response.status_code == 200
    assert response.json()["driver_profile"]["id"] == str(driver.id)


def test_non_driver_role_has_no_driver_profile(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    response = client.get("/api/v1/auth/me", headers=auth_headers(admin))
    assert response.json()["driver_profile"] is None
