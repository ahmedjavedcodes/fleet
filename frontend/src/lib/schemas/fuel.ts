import { z } from "zod"
import { dateStringSchema, dateTimeStringSchema, decimalStringSchema, uuidSchema, vehicleDriverRefsShape } from "./common"
import { fuelReceiptUploadStatusSchema } from "./enums"

// Mirrors backend/app/schemas/fuel.py.

export const fuelReceiptSchema = z.object({
  id: uuidSchema,
  file_path: z.string(),
  file_type: z.string(),
  upload_status: fuelReceiptUploadStatusSchema,
  parsed_data: z.record(z.string(), z.unknown()).nullable(),
})
export type FuelReceipt = z.infer<typeof fuelReceiptSchema>

export const fuelLogSchema = z.object({
  ...vehicleDriverRefsShape,
  id: uuidSchema,
  vehicle_id: uuidSchema,
  driver_id: uuidSchema.nullable(),
  date: dateStringSchema,
  odometer_reading: z.number().int(),
  liters_filled: decimalStringSchema,
  price_per_liter: decimalStringSchema,
  total_cost: decimalStringSchema,
  // Computed by the backend (>= 3-month rolling average, null until there are
  // 3+ prior logs). Display as-is — never recompute (CLAUDE.md §2.1).
  cost_per_km: decimalStringSchema.nullable(),
  is_anomalous: z.boolean(),
  notes: z.string().nullable(),
  // Slip / receipt details.
  po_number: z.string().nullable(),
  payment_method: z.string().nullable(),
  card_used: z.string().nullable(),
  fuel_station_name: z.string().nullable(),
  slip_id: z.string().nullable(),
  created_at: dateTimeStringSchema,
  receipt: fuelReceiptSchema.nullable().optional(),
})
export type FuelLog = z.infer<typeof fuelLogSchema>

export const fuelLogCreateSchema = z
  .object({
    vehicle_id: uuidSchema,
    driver_id: uuidSchema.optional(),
    date: dateStringSchema,
    odometer_reading: z.number().int().positive(),
    liters_filled: z.number().positive(),
    price_per_liter: z.number().positive(),
    total_cost: z.number().positive(),
    notes: z.string().optional(),
    po_number: z.string().optional(),
    payment_method: z.string().optional(),
    card_used: z.string().optional(),
    fuel_station_name: z.string().optional(),
    slip_id: z.string().optional(),
  })
  .strict()
export type FuelLogCreate = z.infer<typeof fuelLogCreateSchema>

// vehicle_id is deliberately not editable on the backend (see FuelLogUpdate's
// docstring) — reassigning a log to a different vehicle isn't supported.
export const fuelLogUpdateSchema = z
  .object({
    driver_id: uuidSchema.optional(),
    date: dateStringSchema.optional(),
    odometer_reading: z.number().int().positive().optional(),
    liters_filled: z.number().positive().optional(),
    price_per_liter: z.number().positive().optional(),
    total_cost: z.number().positive().optional(),
    notes: z.string().optional(),
    po_number: z.string().optional(),
    payment_method: z.string().optional(),
    card_used: z.string().optional(),
    fuel_station_name: z.string().optional(),
    slip_id: z.string().optional(),
  })
  .strict()
export type FuelLogUpdate = z.infer<typeof fuelLogUpdateSchema>

export const vehicleFuelSummarySchema = z.object({
  vehicle_id: uuidSchema,
  plate_number: z.string().nullable(),
  vehicle_name: z.string().nullable(),
  driver_names: z.array(z.string()),
  fill_count: z.number().int(),
  first_fill_date: dateStringSchema.nullable(),
  last_fill_date: dateStringSchema.nullable(),
  total_cost: decimalStringSchema,
  total_liters: decimalStringSchema,
  avg_cost_per_km: decimalStringSchema.nullable(),
})
export type VehicleFuelSummary = z.infer<typeof vehicleFuelSummarySchema>

export const fuelSummaryResponseSchema = z.object({
  month: z.string(),
  period_start: dateStringSchema,
  period_end: dateStringSchema,
  generated_at: dateTimeStringSchema,
  total_cost: decimalStringSchema,
  total_liters: decimalStringSchema,
  avg_cost_per_km: decimalStringSchema.nullable(),
  by_vehicle: z.array(vehicleFuelSummarySchema),
})
export type FuelSummaryResponse = z.infer<typeof fuelSummaryResponseSchema>

export const fuelLogListParamsSchema = z.object({
  vehicle_id: uuidSchema.optional(),
  driver_id: uuidSchema.optional(),
  date_from: dateStringSchema.optional(),
  date_to: dateStringSchema.optional(),
  skip: z.number().int().min(0).optional(),
  limit: z.number().int().min(1).max(500).optional(),
})
export type FuelLogListParams = z.infer<typeof fuelLogListParamsSchema>
