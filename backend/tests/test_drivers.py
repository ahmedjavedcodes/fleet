import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.organization import Organization
from tests.conftest import auth_headers, make_user


@pytest.fixture()
def driver_payload() -> dict:
    return {
        "full_name": "Jamie Driver",
        "license_number": f"LIC-{uuid.uuid4().hex[:8]}",
        "license_expiry": "2030-01-01",
        "phone": "555-0101",
    }


def test_driver_without_user_id_can_be_created(
    client: TestClient, db_session: Session, organization: Organization, driver_payload: dict
) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    response = client.post("/api/v1/drivers", json=driver_payload, headers=auth_headers(admin))
    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] is None

    fetched = client.get(f"/api/v1/drivers/{body['id']}", headers=auth_headers(admin))
    assert fetched.status_code == 200


def test_driver_with_user_id_can_be_created(
    client: TestClient, db_session: Session, organization: Organization, driver_payload: dict
) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    driver_login = make_user(db_session, organization, role=UserRole.driver)

    response = client.post(
        "/api/v1/drivers", json={**driver_payload, "user_id": str(driver_login.id)}, headers=auth_headers(admin)
    )
    assert response.status_code == 201
    assert response.json()["user_id"] == str(driver_login.id)


def test_duplicate_user_id_on_driver_rejected(
    client: TestClient, db_session: Session, organization: Organization, driver_payload: dict
) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    driver_login = make_user(db_session, organization, role=UserRole.driver)

    first = client.post(
        "/api/v1/drivers", json={**driver_payload, "user_id": str(driver_login.id)}, headers=auth_headers(admin)
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/drivers",
        json={**driver_payload, "license_number": f"LIC-{uuid.uuid4().hex[:8]}", "user_id": str(driver_login.id)},
        headers=auth_headers(admin),
    )
    assert second.status_code == 409


def test_driver_user_id_must_belong_to_same_org(
    client: TestClient, db_session: Session, organization: Organization, driver_payload: dict
) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()
    foreign_user = make_user(db_session, other_org, role=UserRole.driver)

    response = client.post(
        "/api/v1/drivers", json={**driver_payload, "user_id": str(foreign_user.id)}, headers=auth_headers(admin)
    )
    assert response.status_code == 404


@pytest.mark.parametrize("role", [UserRole.driver, UserRole.mechanic])
def test_driver_write_routes_forbidden_for_read_only_roles(
    client: TestClient, db_session: Session, organization: Organization, driver_payload: dict, role: UserRole
) -> None:
    reader = make_user(db_session, organization, role=role)
    response = client.post("/api/v1/drivers", json=driver_payload, headers=auth_headers(reader))
    assert response.status_code == 403


@pytest.mark.parametrize("role", [UserRole.admin, UserRole.fleet_manager, UserRole.driver, UserRole.mechanic])
def test_driver_read_routes_allowed_for_all_roles(
    client: TestClient, db_session: Session, organization: Organization, driver_payload: dict, role: UserRole
) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    created = client.post("/api/v1/drivers", json=driver_payload, headers=auth_headers(admin)).json()

    reader = make_user(db_session, organization, role=role)
    list_resp = client.get("/api/v1/drivers", headers=auth_headers(reader))
    get_resp = client.get(f"/api/v1/drivers/{created['id']}", headers=auth_headers(reader))
    assert list_resp.status_code == 200
    assert get_resp.status_code == 200


def test_driver_soft_delete_hides_from_list_and_get(
    client: TestClient, db_session: Session, organization: Organization, driver_payload: dict
) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    created = client.post("/api/v1/drivers", json=driver_payload, headers=auth_headers(admin)).json()

    delete_resp = client.delete(f"/api/v1/drivers/{created['id']}", headers=auth_headers(admin))
    assert delete_resp.status_code == 204

    get_resp = client.get(f"/api/v1/drivers/{created['id']}", headers=auth_headers(admin))
    assert get_resp.status_code == 404

    list_resp = client.get("/api/v1/drivers", headers=auth_headers(admin))
    assert all(d["id"] != created["id"] for d in list_resp.json())


def test_driver_org_scoping(client: TestClient, db_session: Session, organization: Organization, driver_payload: dict) -> None:
    admin_a = make_user(db_session, organization, role=UserRole.admin)
    client.post("/api/v1/drivers", json=driver_payload, headers=auth_headers(admin_a))

    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()
    admin_b = make_user(db_session, other_org, role=UserRole.admin)

    list_resp = client.get("/api/v1/drivers", headers=auth_headers(admin_b))
    assert list_resp.status_code == 200
    assert list_resp.json() == []
