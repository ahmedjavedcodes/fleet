from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.driver import DriverResponse
from app.schemas.organization import OrganizationResponse
from app.schemas.user import UserResponse


class RegisterRequest(BaseModel):
    organization_name: str
    organization_slug: str = Field(pattern=r"^[a-z0-9-]+$", min_length=2, max_length=100)
    admin_email: EmailStr
    admin_password: str = Field(min_length=8)
    admin_full_name: str


class RegisterResponse(BaseModel):
    organization: OrganizationResponse
    user: UserResponse


class LoginRequest(BaseModel):
    # Email is unique per-organization, not globally -- org_slug disambiguates
    # which organization to check credentials against.
    org_slug: str
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user: UserResponse
    organization: OrganizationResponse
    driver_profile: DriverResponse | None = None
