import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.enums import UserRole
from app.models.organization import Organization
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest

_LOGIN_ERROR = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")


def register_organization(db: Session, data: RegisterRequest) -> tuple[Organization, User]:
    """Single transaction: Organization + its first (admin) User, or neither."""
    existing = db.execute(select(Organization).where(Organization.slug == data.organization_slug)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Organization slug already exists")

    organization = Organization(id=uuid.uuid4(), name=data.organization_name, slug=data.organization_slug)
    db.add(organization)
    db.flush()  # assign organization.id within the transaction, no commit yet

    admin_user = User(
        id=uuid.uuid4(),
        organization_id=organization.id,
        email=data.admin_email,
        hashed_password=hash_password(data.admin_password),
        full_name=data.admin_full_name,
        role=UserRole.admin,
        created_by=None,  # bootstrap case -- no prior user exists yet
    )
    db.add(admin_user)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Organization slug already exists") from exc

    db.refresh(organization)
    db.refresh(admin_user)
    return organization, admin_user


def authenticate(db: Session, data: LoginRequest) -> User:
    """Generic 401 for every failure mode (missing org, missing user, inactive user,
    wrong password) -- never reveals which part was wrong."""
    organization = db.execute(select(Organization).where(Organization.slug == data.org_slug)).scalar_one_or_none()
    if organization is None:
        raise _LOGIN_ERROR

    user = db.execute(
        select(User).where(
            User.organization_id == organization.id,
            User.email == data.email,
            User.is_deleted.is_(False),
        )
    ).scalar_one_or_none()

    if user is None or not user.is_active or not verify_password(data.password, user.hashed_password):
        raise _LOGIN_ERROR

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user
