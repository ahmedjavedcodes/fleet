from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_current_driver_profile, get_current_user
from app.core.security import create_access_token
from app.models.driver import Driver
from app.models.organization import Organization
from app.models.user import User
from app.schemas.auth import LoginRequest, MeResponse, RegisterRequest, RegisterResponse, TokenResponse
from app.schemas.driver import DriverResponse
from app.schemas.organization import OrganizationResponse
from app.schemas.user import UserResponse
from app.services import auth_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, db: Session = Depends(get_db)) -> RegisterResponse:
    organization, user = auth_service.register_organization(db, data)
    return RegisterResponse(
        organization=OrganizationResponse.model_validate(organization),
        user=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = auth_service.authenticate(db, data)
    settings = get_settings()
    token = create_access_token(user_id=user.id, organization_id=user.organization_id, role=user.role)
    return TokenResponse(access_token=token, expires_in=settings.access_token_expire_minutes * 60)


@router.get("/me", response_model=MeResponse)
def me(
    current_user: User = Depends(get_current_user),
    driver_profile: Driver | None = Depends(get_current_driver_profile),
    db: Session = Depends(get_db),
) -> MeResponse:
    organization = db.get(Organization, current_user.organization_id)
    return MeResponse(
        user=UserResponse.model_validate(current_user),
        organization=OrganizationResponse.model_validate(organization),
        driver_profile=DriverResponse.model_validate(driver_profile) if driver_profile is not None else None,
    )
