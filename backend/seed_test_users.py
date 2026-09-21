"""Seed one real, logged-in user per RBAC role into a dedicated test
organization, for manually testing the Fleet Registry Agent against a real
running backend (as opposed to ai_agents/generate_test_tokens.py, which
mints unsigned-against-nothing tokens for unit-test-style use).

There is no public API for creating non-admin users (Plan 00's /auth/register
only ever creates the bootstrap admin) -- direct DB insertion is the
established, documented pattern for this in the codebase itself; see
backend/tests/conftest.py's make_user() docstring. This script does the same
thing conftest.py does, just against the real dev database instead of a
transaction that gets rolled back.

Idempotent and additive only: uses a distinct slug/org so it never touches
or collides with any organization already in the database, and re-running it
reuses whatever it already created instead of erroring or duplicating.

Run from backend/ with the backend's own venv:

    .venv\\Scripts\\python seed_test_users.py
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import create_access_token, hash_password, verify_password
from app.models.enums import UserRole
from app.models.organization import Organization
from app.models.user import User

ORG_NAME = "Fleet Registry Agent Test Org"
ORG_SLUG = "fleet-registry-agent-test"
# email-validator (used by Pydantic's EmailStr, re-validated on every read via
# UserResponse) rejects RFC 2606 special-use TLDs like .test/.example/.local
# outright -- .dev is a real, non-reserved gTLD, so it passes that check.
EMAIL_DOMAIN = f"{ORG_SLUG}.dev"
PASSWORD = "TestPass123!"

_ROLES = [UserRole.admin, UserRole.fleet_manager, UserRole.driver, UserRole.mechanic]


def _get_or_create_organization(db) -> Organization:
    org = db.execute(select(Organization).where(Organization.slug == ORG_SLUG)).scalar_one_or_none()
    if org is not None:
        return org
    org = Organization(id=uuid.uuid4(), name=ORG_NAME, slug=ORG_SLUG)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _get_or_create_user(db, org: Organization, role: UserRole) -> User:
    email = f"{role.value}@{EMAIL_DOMAIN}"
    user = db.execute(
        select(User).where(User.organization_id == org.id, User.email == email)
    ).scalar_one_or_none()
    if user is not None:
        return user
    user = User(
        id=uuid.uuid4(),
        organization_id=org.id,
        email=email,
        hashed_password=hash_password(PASSWORD),
        full_name=f"Test {role.value.replace('_', ' ').title()}",
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def main() -> None:
    db = SessionLocal()
    try:
        org = _get_or_create_organization(db)

        print(f"Organization:      {ORG_NAME}")
        print(f"Organization ID:   {org.id}")
        print(f"Organization slug: {org.slug}  (for POST /api/v1/auth/login's org_slug field)")
        print(f"Shared password:   {PASSWORD}")
        print()

        for role in _ROLES:
            user = _get_or_create_user(db, org, role)
            assert verify_password(PASSWORD, user.hashed_password), (
                f"seeded {role.value} user's stored hash doesn't match {PASSWORD!r} -- "
                "delete this user row and re-run to reseed it"
            )
            token = create_access_token(user_id=user.id, organization_id=user.organization_id, role=user.role)

            print(f"=== {role.value} ===")
            print(f"email: {user.email}")
            print(f"user_id: {user.id}")
            print(f"JWT: {token}")
            print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
