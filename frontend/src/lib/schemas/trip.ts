import { z } from "zod"
import { dateStringSchema, dateTimeStringSchema, decimalStringSchema, uuidSchema, vehicleDriverRefsShape } from "./common"

// Mirrors backend/app/schemas/accountability.py TripLog*.
// Both ends of a trip are required — there is no in-progress trip state.

export const tripLogSchema = z.object({
  ...vehicleDriverRefsShape,
  id: uuidSchema,
  driver_id: uuidSchema,
  vehicle_id: uuidSchema,
  start_time: dateTimeStringSchema,
  end_time: dateTimeStringSchema,
  start_odometer: z.number().int(),
  end_odometer: z.number().int(),
  distance_km: z.number().int(),
  fuel_consumed: decimalStringSchema.nullable(),
  notes: z.string().nullable(),
  created_at: dateTimeStringSchema,
})
export type TripLog = z.infer<typeof tripLogSchema>

export const tripLogCreateSchema = z
  .object({
    driver_id: uuidSchema,
    vehicle_id: uuidSchema,
    start_time: dateTimeStringSchema,
    end_time: dateTimeStringSchema,
    start_odometer: z.number().int().positive(),
    end_odometer: z.number().int().positive(),
    fuel_consumed: z.number().min(0).optional(),
    notes: z.string().optional(),
  })
  .strict()
export type TripLogCreate = z.infer<typeof tripLogCreateSchema>

export const tripLogListParamsSchema = z.object({
  driver_id: uuidSchema.optional(),
  vehicle_id: uuidSchema.optional(),
  date_from: dateStringSchema.optional(),
  date_to: dateStringSchema.optional(),
})
export type TripLogListParams = z.infer<typeof tripLogListParamsSchema>
