// Mirrors backend/app/schemas/vehicle.py
import type { VehicleFuelType, VehicleStatus } from "./enums";

export interface VehicleBase {
  plate_number: string;
  make: string;
  model: string;
  year: number;
  vin: string;
  fuel_type: VehicleFuelType;
  status: VehicleStatus;
  service_interval_km: number | null;
  service_interval_months: number | null;
}

export interface VehicleCreate extends VehicleBase {
  current_odometer: number;
}

export type VehicleUpdate = Partial<VehicleBase & { current_odometer: number }>;

export interface VehicleResponse extends VehicleBase {
  id: string;
  organization_id: string;
  current_odometer: number;
}
