// Mirrors backend/app/schemas/vehicle.py::VehicleCreate.
// Keep in sync with src/lib/types/vehicle.ts and the backend schema together.
import { z } from "zod";

const currentYear = new Date().getFullYear();

export const vehicleCreateSchema = z.object({
  plate_number: z.string().min(1, "Plate number is required"),
  make: z.string().min(1, "Make is required"),
  model: z.string().min(1, "Model is required"),
  year: z
    .number({ invalid_type_error: "Year is required" })
    .int()
    .min(1980, "Year looks too old")
    .max(currentYear + 1, "Year can't be in the future"),
  vin: z.string().min(1, "VIN is required"),
  fuel_type: z.enum(["diesel", "petrol", "hybrid", "electric"]),
  status: z.enum(["active", "maintenance", "retired"]).default("active"),
  service_interval_km: z.number().int().positive().nullable().optional(),
  service_interval_months: z.number().int().positive().nullable().optional(),
  current_odometer: z.number().int().min(0).default(0),
});

export type VehicleCreateFormValues = z.infer<typeof vehicleCreateSchema>;
