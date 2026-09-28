import { z } from "zod"
import { dateStringSchema, dateTimeStringSchema, decimalStringSchema, uuidSchema } from "./common"
import { serviceTypeSchema } from "./enums"

// Mirrors backend/app/schemas/maintenance.py.

export const partUsedSchema = z.object({
  part_id: uuidSchema,
  qty: z.number().int().positive(),
})
export type PartUsed = z.infer<typeof partUsedSchema>

export const lowStockAlertSchema = z.object({
  part_id: uuidSchema,
  low_stock_alert: z.boolean(),
})
export type LowStockAlert = z.infer<typeof lowStockAlertSchema>

export const mechanicReportSchema = z.object({
  id: uuidSchema,
  maintenance_log_id: uuidSchema,
  diagnostic_notes: z.string().nullable(),
  findings: z.string().nullable(),
  actions_taken: z.string().nullable(),
  parts_used: z.array(partUsedSchema),
  recommendations: z.string().nullable(),
  // Only populated on the create response — empty on later GETs.
  low_stock_alerts: z.array(lowStockAlertSchema),
})
export type MechanicReport = z.infer<typeof mechanicReportSchema>

export const mechanicReportCreateSchema = z
  .object({
    diagnostic_notes: z.string().optional(),
    findings: z.string().optional(),
    actions_taken: z.string().optional(),
    parts_used: z.array(partUsedSchema).default([]),
    recommendations: z.string().optional(),
  })
  .strict()
export type MechanicReportCreate = z.infer<typeof mechanicReportCreateSchema>

export const maintenanceLogSchema = z.object({
  id: uuidSchema,
  vehicle_id: uuidSchema,
  date: dateStringSchema,
  odometer_at_service: z.number().int(),
  service_type: serviceTypeSchema,
  description: z.string().nullable(),
  cost: decimalStringSchema.nullable(),
  mechanic_name: z.string().nullable(),
  next_due_km: z.number().int().nullable(),
  next_due_date: dateStringSchema.nullable(),
  created_at: dateTimeStringSchema,
  mechanic_report: mechanicReportSchema.nullable().optional(),
})
export type MaintenanceLog = z.infer<typeof maintenanceLogSchema>

export const maintenanceLogCreateSchema = z
  .object({
    vehicle_id: uuidSchema,
    date: dateStringSchema,
    odometer_at_service: z.number().int().positive(),
    service_type: serviceTypeSchema,
    description: z.string().optional(),
    cost: z.number().min(0).optional(),
    mechanic_name: z.string().optional(),
  })
  .strict()
export type MaintenanceLogCreate = z.infer<typeof maintenanceLogCreateSchema>

export const maintenanceLogUpdateSchema = z
  .object({
    date: dateStringSchema.optional(),
    odometer_at_service: z.number().int().positive().optional(),
    service_type: serviceTypeSchema.optional(),
    description: z.string().optional(),
    cost: z.number().min(0).optional(),
    mechanic_name: z.string().optional(),
  })
  .strict()
export type MaintenanceLogUpdate = z.infer<typeof maintenanceLogUpdateSchema>

export const maintenanceLogListParamsSchema = z.object({
  vehicle_id: uuidSchema.optional(),
  service_type: serviceTypeSchema.optional(),
  date_from: dateStringSchema.optional(),
  date_to: dateStringSchema.optional(),
})
export type MaintenanceLogListParams = z.infer<typeof maintenanceLogListParamsSchema>

// Shared shape of upcoming/overdue maintenance items.
const maintenanceCalendarItemBaseSchema = z.object({
  vehicle_id: uuidSchema,
  plate_number: z.string(),
  service_type: serviceTypeSchema,
  next_due_km: z.number().int().nullable(),
  next_due_date: dateStringSchema.nullable(),
  current_odometer: z.number().int(),
  km_remaining: z.number().int().nullable(),
})

export const upcomingMaintenanceItemSchema = maintenanceCalendarItemBaseSchema
export type UpcomingMaintenanceItem = z.infer<typeof upcomingMaintenanceItemSchema>

export const overdueMaintenanceItemSchema = maintenanceCalendarItemBaseSchema
export type OverdueMaintenanceItem = z.infer<typeof overdueMaintenanceItemSchema>
