// Mirrors backend/app/schemas/auth.py
import type { DriverResponse } from "./driver";
import type { OrganizationResponse } from "./organization";
import type { UserResponse } from "./user";

export interface RegisterRequest {
  organization_name: string;
  organization_slug: string;
  admin_email: string;
  admin_password: string;
  admin_full_name: string;
}

export interface RegisterResponse {
  organization: OrganizationResponse;
  user: UserResponse;
}

export interface LoginRequest {
  // Email is unique per-organization, not globally — org_slug disambiguates
  // which organization to check credentials against.
  org_slug: string;
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface MeResponse {
  user: UserResponse;
  organization: OrganizationResponse;
  driver_profile: DriverResponse | null;
}
