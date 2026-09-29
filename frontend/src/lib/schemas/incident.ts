import { z } from "zod"
import { dateStringSchema, dateTimeStringSchema, decimalStringSchema, uuidSchema, vehicleDriverRefsShape } from "./common"
import { incidentResolutionStatusSchema, incidentSeveritySchema, incidentTypeSchema } from "./enums"

// Mirrors backend/app/schemas/accountability.py IncidentLog*.
// Incidents are immutable: only resolution_status/resolution_notes can ever
// change (CLAUDE.md §2.1) — enforced by IncidentLogResolutionUpdate's shape
// on the backend (extra="forbid"), not just a convention here.

export const incidentLogSchema = z.object({
  ...vehicleDriverRefsShape,
  id: uuidSchema,
  driver_id: uuidSchema.nullable(),
  vehicle_id: uuidSchema,
  incident_type: incidentTypeSchema,
  date: dateStringSchema,
  // Full timestamp; null on records that pre-date the field.
  incident_time: dateTimeStringSchema.nullable(),
  severity: incidentSeveritySchema,
  description: z.string(),
  location_description: z.string().nullable(),
  location_area: z.string().nullable(),
  remarks: z.string().nullable(),
  attachment_url: z.string().nullable(),
  estimated_cost: decimalStringSchema.nullable(),
  resolution_status: incidentResolutionStatusSchema,
  resolution_notes: z.string().nullable(),
  created_at: dateTimeStringSchema,
})
export type IncidentLog = z.infer<typeof incidentLogSchema>

export const incidentLogCreateSchema = z
  .object({
    driver_id: uuidSchema.optional(),
    vehicle_id: uuidSchema,
    incident_type: incidentTypeSchema,
    date: dateStringSchema,
    incident_time: dateTimeStringSchema.optional(),
    severity: incidentSeveritySchema,
    description: z.string().min(1, "Description is required"),
    location_description: z.string().optional(),
    location_area: z.string().optional(),
    remarks: z.string().optional(),
    attachment_url: z.string().optional(),
    estimated_cost: z.number().min(0).optional(),
  })
  .strict()
export type IncidentLogCreate = z.infer<typeof incidentLogCreateSchema>

export const incidentLogResolutionUpdateSchema = z
  .object({
    resolution_status: incidentResolutionStatusSchema,
    resolution_notes: z.string().optional(),
  })
  .strict()
export type IncidentLogResolutionUpdate = z.infer<typeof incidentLogResolutionUpdateSchema>

export const incidentLogListParamsSchema = z.object({
  type: incidentTypeSchema.optional(),
  severity: incidentSeveritySchema.optional(),
  status: incidentResolutionStatusSchema.optional(),
})
export type IncidentLogListParams = z.infer<typeof incidentLogListParamsSchema>
