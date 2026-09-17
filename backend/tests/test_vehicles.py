import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.organization import Organization
from tests.conftest import auth_headers, make_user


@pytest.fixture()
def vehicle_payload() -> dict:
    return {
        "plate_number": f"PLT-{uuid.uuid4().hex[:6]}",
        "make": "Isuzu",
        "model": "NPR",
        "year": 2019,
        "vin": uuid.uuid4().hex[:17],
        "fuel_type": "diesel",
        "service_interval_km": 10000,
        "service_interval_months": 6,
    }


def test_create_vehicle_defaults_odometer_to_zero(
    client: TestClient, db_session: Session, organization: Organization, vehicle_payload: dict
) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    response = client.post("/api/v1/vehicles", json=vehicle_payload, headers=auth_headers(admin))
    assert response.status_code == 201
    assert response.json()["current_odometer"] == 0
    assert response.json()["status"] == "active"


def test_vehicle_plate_number_unique_per_org(
    client: TestClient, db_session: Session, organization: Organization, vehicle_payload: dict
) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    first = client.post("/api/v1/vehicles", json=vehicle_payload, headers=auth_headers(admin))
    assert first.status_code == 201

    duplicate = {**vehicle_payload, "vin": uuid.uuid4().hex[:17]}
    second = client.post("/api/v1/vehicles", json=duplicate, headers=auth_headers(admin))
    assert second.status_code >= 400


def test_vehicle_update_partial(
    client: TestClient, db_session: Session, organization: Organization, vehicle_payload: dict
) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    created = client.post("/api/v1/vehicles", json=vehicle_payload, headers=auth_headers(admin)).json()

    response = client.put(f"/api/v1/vehicles/{created['id']}", json={"status": "maintenance"}, headers=auth_headers(admin))
    assert response.status_code == 200
    assert response.json()["status"] == "maintenance"
    assert response.json()["make"] == vehicle_payload["make"]  # untouched fields unchanged


def test_vehicle_get_missing_returns_404(client: TestClient, db_session: Session, organization: Organization) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    response = client.get(f"/api/v1/vehicles/{uuid.uuid4()}", headers=auth_headers(admin))
    assert response.status_code == 404


def test_vehicle_org_scoping(
    client: TestClient, db_session: Session, organization: Organization, vehicle_payload: dict
) -> None:
    admin_a = make_user(db_session, organization, role=UserRole.admin)
    created = client.post("/api/v1/vehicles", json=vehicle_payload, headers=auth_headers(admin_a)).json()

    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()
    admin_b = make_user(db_session, other_org, role=UserRole.admin)

    get_resp = client.get(f"/api/v1/vehicles/{created['id']}", headers=auth_headers(admin_b))
    assert get_resp.status_code == 404

    list_resp = client.get("/api/v1/vehicles", headers=auth_headers(admin_b))
    assert list_resp.json() == []
