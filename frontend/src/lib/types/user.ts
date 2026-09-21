// Mirrors backend/app/schemas/user.py::UserResponse. Never carries a password
// field — the backend response never includes one either.
import type { UserRole } from "./enums";

export interface UserResponse {
  id: string;
  organization_id: string;
  email: string;
  full_name: string;
  phone: string | null;
  role: UserRole;
  is_active: boolean;
  last_login_at: string | null;
}
