import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.organization import Organization
from app.models.supplier import Supplier
from tests.conftest import auth_headers, make_user


@pytest.fixture()
def supplier_payload() -> dict:
    return {"name": f"Acme Parts {uuid.uuid4().hex[:6]}", "contact_email": "sales@example.com", "phone": "555-0200"}


def test_supplier_create_and_reliability_score_is_response_only(
    client: TestClient, db_session: Session, organization: Organization, supplier_payload: dict
) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    response = client.post(
        "/api/v1/suppliers", json={**supplier_payload, "reliability_score": 0.99}, headers=auth_headers(admin)
    )
    assert response.status_code == 201
    # reliability_score isn't in SupplierCreate at all -- extra field is ignored, never stored.
    assert response.json()["reliability_score"] is None


@pytest.mark.parametrize("role", [UserRole.driver, UserRole.mechanic])
def test_supplier_write_forbidden_for_read_only_roles(
    client: TestClient, db_session: Session, organization: Organization, supplier_payload: dict, role: UserRole
) -> None:
    reader = make_user(db_session, organization, role=role)
    response = client.post("/api/v1/suppliers", json=supplier_payload, headers=auth_headers(reader))
    assert response.status_code == 403


@pytest.mark.parametrize("role", [UserRole.admin, UserRole.fleet_manager, UserRole.driver, UserRole.mechanic])
def test_supplier_list_allowed_for_all_roles(
    client: TestClient, db_session: Session, organization: Organization, supplier_payload: dict, role: UserRole
) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    client.post("/api/v1/suppliers", json=supplier_payload, headers=auth_headers(admin))

    reader = make_user(db_session, organization, role=role)
    response = client.get("/api/v1/suppliers", headers=auth_headers(reader))
    assert response.status_code == 200


def test_supplier_sort_by_reliability_score_nulls_last(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    scored = Supplier(id=uuid.uuid4(), organization_id=organization.id, name="Scored Co", reliability_score=0.9)
    unscored = Supplier(id=uuid.uuid4(), organization_id=organization.id, name="Unscored Co", reliability_score=None)
    db_session.add_all([scored, unscored])
    db_session.commit()

    admin = make_user(db_session, organization, role=UserRole.admin)
    response = client.get("/api/v1/suppliers?sort=reliability_score", headers=auth_headers(admin))
    assert response.status_code == 200
    names = [s["name"] for s in response.json()]
    assert names.index("Scored Co") < names.index("Unscored Co")


def test_supplier_update(client: TestClient, db_session: Session, organization: Organization, supplier_payload: dict) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    created = client.post("/api/v1/suppliers", json=supplier_payload, headers=auth_headers(admin)).json()

    response = client.put(f"/api/v1/suppliers/{created['id']}", json={"phone": "555-9999"}, headers=auth_headers(admin))
    assert response.status_code == 200
    assert response.json()["phone"] == "555-9999"


def test_supplier_org_scoping(
    client: TestClient, db_session: Session, organization: Organization, supplier_payload: dict
) -> None:
    admin_a = make_user(db_session, organization, role=UserRole.admin)
    client.post("/api/v1/suppliers", json=supplier_payload, headers=auth_headers(admin_a))

    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()
    admin_b = make_user(db_session, other_org, role=UserRole.admin)

    response = client.get("/api/v1/suppliers", headers=auth_headers(admin_b))
    assert response.json() == []
