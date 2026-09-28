import { z } from "zod"
import { dateTimeStringSchema, decimalStringSchema, uuidSchema } from "./common"
import { vehicleConditionSchema } from "./enums"
import { incidentResolutionStatusSchema, incidentSeveritySchema, incidentTypeSchema } from "./enums"

// Mirrors backend/app/schemas/accountability.py TimelineEntry. The backend
// types `summary` as a plain `dict`, but each `record_type` has a fixed shape
// in practice (it's built from the trip/report/incident response models) —
// modeling it as a discriminated union here catches a shape drift as a
// schema-parse error instead of letting `any`-shaped data reach the UI.

const tripSummarySchema = z.object({
  driver_id: uuidSchema,
  vehicle_id: uuidSchema,
  start_time: dateTimeStringSchema,
  end_time: dateTimeStringSchema,
  start_odometer: z.number().int(),
  end_odometer: z.number().int(),
  distance_km: z.number().int(),
  fuel_consumed: decimalStringSchema.nullable(),
  notes: z.string().nullable(),
})

const reportSummarySchema = z.object({
  driver_id: uuidSchema,
  vehicle_id: uuidSchema,
  shift_date: z.string(),
  vehicle_condition: vehicleConditionSchema,
  handover_notes: z.string().nullable(),
  issues_reported: z.string().nullable(),
})

const incidentSummarySchema = z.object({
  driver_id: uuidSchema.nullable(),
  vehicle_id: uuidSchema,
  incident_type: incidentTypeSchema,
  date: z.string(),
  severity: incidentSeveritySchema,
  description: z.string(),
  location_description: z.string().nullable(),
  estimated_cost: decimalStringSchema.nullable(),
  resolution_status: incidentResolutionStatusSchema,
  resolution_notes: z.string().nullable(),
})

export const timelineEntrySchema = z.discriminatedUnion("record_type", [
  z.object({ record_type: z.literal("trip"), id: uuidSchema, date: dateTimeStringSchema, summary: tripSummarySchema }),
  z.object({ record_type: z.literal("report"), id: uuidSchema, date: dateTimeStringSchema, summary: reportSummarySchema }),
  z.object({
    record_type: z.literal("incident"),
    id: uuidSchema,
    date: dateTimeStringSchema,
    summary: incidentSummarySchema,
  }),
])
export type TimelineEntry = z.infer<typeof timelineEntrySchema>

export const timelineResponseSchema = z.array(timelineEntrySchema)
export type TimelineResponse = z.infer<typeof timelineResponseSchema>
