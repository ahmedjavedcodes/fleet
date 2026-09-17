import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.driver import Driver
from app.models.enums import UserRole
from app.models.user import User

# tokenUrl is documentation metadata for the Swagger "Authorize" button only --
# our /auth/login endpoint takes a JSON body, not an OAuth2 form.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    if token is None:
        raise _CREDENTIALS_ERROR
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise _CREDENTIALS_ERROR from exc

    user_id = payload.get("sub")
    org_id = payload.get("org")
    if user_id is None or org_id is None:
        raise _CREDENTIALS_ERROR

    user = db.get(User, uuid.UUID(user_id))
    if user is None or user.is_deleted or not user.is_active:
        raise _CREDENTIALS_ERROR
    if str(user.organization_id) != org_id:
        raise _CREDENTIALS_ERROR
    return user


def require_role(*roles: UserRole):
    """The only place role-gating logic lives. Deliberately checks the freshly
    fetched User.role (not the JWT's role claim): get_current_user already loads
    the row for the is_active check, so re-checking role here is free and means a
    role change takes effect immediately instead of only after the old JWT expires."""

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")
        return current_user

    return dependency


def get_current_driver_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Driver | None:
    """Returns None (not an error) when current_user isn't a driver, or is a
    driver-role user with no linked Driver row yet. Callers doing row-level 'own
    only' filtering must handle None explicitly -- e.g. return an empty list."""
    if current_user.role != UserRole.driver:
        return None
    stmt = select(Driver).where(
        Driver.user_id == current_user.id,
        Driver.organization_id == current_user.organization_id,
        Driver.is_deleted.is_(False),
    )
    return db.execute(stmt).scalar_one_or_none()
