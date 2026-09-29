import { z } from "zod"
import { uuidSchema } from "./common"
import { vehicleFuelTypeSchema, vehicleOwnershipTypeSchema, vehicleStatusSchema } from "./enums"

// Mirrors backend/app/schemas/vehicle.py.

export const vehicleSchema = z.object({
  id: uuidSchema,
  organization_id: uuidSchema,
  plate_number: z.string(),
  make: z.string(),
  model: z.string(),
  year: z.number().int(),
  vin: z.string(),
  fuel_type: vehicleFuelTypeSchema,
  status: vehicleStatusSchema,
  current_odometer: z.number().int(),
  service_interval_km: z.number().int().nullable(),
  service_interval_months: z.number().int().nullable(),
  engine_number: z.string().nullable(),
  chassis_number: z.string().nullable(),
  ownership_type: vehicleOwnershipTypeSchema,
  // User who registered the record — set server-side, never sent by the client.
  added_by: uuidSchema.nullable(),
})
export type Vehicle = z.infer<typeof vehicleSchema>

const currentYear = new Date().getFullYear()

export const vehicleCreateSchema = z
  .object({
    plate_number: z.string().min(1, "Plate number is required"),
    make: z.string().min(1, "Make is required"),
    model: z.string().min(1, "Model is required"),
    year: z.number().int().min(1980).max(currentYear + 1),
    vin: z.string().min(1, "VIN is required"),
    fuel_type: vehicleFuelTypeSchema,
    status: vehicleStatusSchema.default("active"),
    service_interval_km: z.number().int().positive().optional(),
    service_interval_months: z.number().int().positive().optional(),
    current_odometer: z.number().int().min(0).default(0),
    engine_number: z.string().optional(),
    chassis_number: z.string().optional(),
    ownership_type: vehicleOwnershipTypeSchema.default("owner"),
  })
  .strict()
export type VehicleCreate = z.infer<typeof vehicleCreateSchema>

export const vehicleUpdateSchema = z
  .object({
    plate_number: z.string().min(1).optional(),
    make: z.string().min(1).optional(),
    model: z.string().min(1).optional(),
    year: z.number().int().min(1980).max(currentYear + 1).optional(),
    vin: z.string().min(1).optional(),
    current_odometer: z.number().int().min(0).optional(),
    fuel_type: vehicleFuelTypeSchema.optional(),
    status: vehicleStatusSchema.optional(),
    service_interval_km: z.number().int().positive().optional(),
    service_interval_months: z.number().int().positive().optional(),
    engine_number: z.string().optional(),
    chassis_number: z.string().optional(),
    ownership_type: vehicleOwnershipTypeSchema.optional(),
  })
  .strict()
export type VehicleUpdate = z.infer<typeof vehicleUpdateSchema>
