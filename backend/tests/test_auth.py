import uuid

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.enums import UserRole
from app.models.organization import Organization
from app.models.user import User
from tests.conftest import auth_headers, make_user


def _register_payload(**overrides: object) -> dict:
    payload = {
        "organization_name": "Acme Fleet",
        "organization_slug": f"acme-{uuid.uuid4().hex[:8]}",
        "admin_email": "admin@example.com",
        "admin_password": "supersecret1",
        "admin_full_name": "Ada Min",
    }
    payload.update(overrides)
    return payload


def test_register_creates_org_and_admin_user(client: TestClient, db_session: Session) -> None:
    payload = _register_payload()
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["organization"]["slug"] == payload["organization_slug"]
    assert body["user"]["role"] == "admin"
    assert body["user"]["email"] == payload["admin_email"]

    org = db_session.execute(select(Organization).where(Organization.slug == payload["organization_slug"])).scalar_one()
    users = db_session.execute(select(User).where(User.organization_id == org.id)).scalars().all()
    assert len(users) == 1
    assert users[0].role.value == "admin"
    assert users[0].created_by is None  # bootstrap case


def test_register_duplicate_slug_rejected(client: TestClient) -> None:
    payload = _register_payload()
    first = client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    second = client.post("/api/v1/auth/register", json=_register_payload(organization_slug=payload["organization_slug"]))
    assert second.status_code == 409


def test_org_scoping_on_email_uniqueness(client: TestClient) -> None:
    same_email = "shared@example.com"
    first = client.post("/api/v1/auth/register", json=_register_payload(admin_email=same_email))
    second = client.post("/api/v1/auth/register", json=_register_payload(admin_email=same_email))
    assert first.status_code == 201
    assert second.status_code == 201


def test_login_returns_jwt_with_expected_claims(client: TestClient) -> None:
    payload = _register_payload()
    client.post("/api/v1/auth/register", json=payload)

    response = client.post(
        "/api/v1/auth/login",
        json={"org_slug": payload["organization_slug"], "email": payload["admin_email"], "password": payload["admin_password"]},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]

    settings = get_settings()
    claims = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    assert claims["role"] == "admin"
    assert "sub" in claims
    assert "org" in claims


def test_login_requires_correct_org_scope(client: TestClient) -> None:
    payload_a = _register_payload(admin_email="dup@example.com")
    payload_b = _register_payload(admin_email="dup@example.com", admin_password="differentpass1")
    client.post("/api/v1/auth/register", json=payload_a)
    client.post("/api/v1/auth/register", json=payload_b)

    # Correct org + correct password for org A succeeds.
    ok = client.post(
        "/api/v1/auth/login",
        json={"org_slug": payload_a["organization_slug"], "email": "dup@example.com", "password": payload_a["admin_password"]},
    )
    assert ok.status_code == 200

    # Org A's password does not work against org B, even with the same email.
    wrong_org = client.post(
        "/api/v1/auth/login",
        json={"org_slug": payload_b["organization_slug"], "email": "dup@example.com", "password": payload_a["admin_password"]},
    )
    assert wrong_org.status_code == 401


def test_login_rejects_wrong_password(client: TestClient) -> None:
    payload = _register_payload()
    client.post("/api/v1/auth/register", json=payload)
    response = client.post(
        "/api/v1/auth/login",
        json={"org_slug": payload["organization_slug"], "email": payload["admin_email"], "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_login_rejects_inactive_user(client: TestClient, db_session: Session, organization: Organization) -> None:
    user = make_user(db_session, organization, role=UserRole.admin, email="inactive@example.com", password="password123", is_active=False)
    response = client.post(
        "/api/v1/auth/login",
        json={"org_slug": organization.slug, "email": user.email, "password": "password123"},
    )
    assert response.status_code == 401


def test_me_returns_current_user_and_organization(client: TestClient, db_session: Session, organization: Organization) -> None:
    user = make_user(db_session, organization, role=UserRole.admin, email="me@example.com")
    response = client.get("/api/v1/auth/me", headers=auth_headers(user))
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "me@example.com"
    assert body["organization"]["id"] == str(organization.id)
    assert body["driver_profile"] is None


def test_me_rejects_missing_token(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
