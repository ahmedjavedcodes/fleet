// Mirrors backend/app/schemas/driver.py
import type { DriverStatus } from "./enums";

export interface DriverResponse {
  id: string;
  organization_id: string;
  user_id: string | null;
  full_name: string;
  license_number: string;
  license_expiry: string;
  phone: string;
  status: DriverStatus;
}
