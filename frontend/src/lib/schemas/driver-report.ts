import { z } from "zod"
import { dateStringSchema, dateTimeStringSchema, uuidSchema, vehicleDriverRefsShape } from "./common"
import { vehicleConditionSchema } from "./enums"

// Mirrors backend/app/schemas/accountability.py DriverReport*.
// Append-only: create + response only — the backend has no update schema and
// PATCH/PUT return 405. Never render an edit action for these (CLAUDE.md §2.1).

export const driverReportSchema = z.object({
  ...vehicleDriverRefsShape,
  id: uuidSchema,
  driver_id: uuidSchema,
  vehicle_id: uuidSchema,
  shift_date: dateStringSchema,
  vehicle_condition: vehicleConditionSchema,
  handover_notes: z.string().nullable(),
  issues_reported: z.string().nullable(),
  created_at: dateTimeStringSchema,
})
export type DriverReport = z.infer<typeof driverReportSchema>

export const driverReportCreateSchema = z
  .object({
    driver_id: uuidSchema,
    vehicle_id: uuidSchema,
    shift_date: dateStringSchema,
    vehicle_condition: vehicleConditionSchema,
    handover_notes: z.string().optional(),
    issues_reported: z.string().optional(),
  })
  .strict()
export type DriverReportCreate = z.infer<typeof driverReportCreateSchema>

export const driverReportListParamsSchema = z.object({
  driver_id: uuidSchema.optional(),
  vehicle_id: uuidSchema.optional(),
  condition: vehicleConditionSchema.optional(),
})
export type DriverReportListParams = z.infer<typeof driverReportListParamsSchema>
