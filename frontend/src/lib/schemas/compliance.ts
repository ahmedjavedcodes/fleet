import { z } from "zod"
import { dateStringSchema, uuidSchema } from "./common"
import { complianceStatusSchema, serviceTypeSchema } from "./enums"

// Mirrors backend/app/schemas/compliance.py.

export const complianceRuleSchema = z.object({
  id: uuidSchema,
  organization_id: uuidSchema,
  vehicle_make: z.string(),
  vehicle_model: z.string(),
  service_type: serviceTypeSchema,
  interval_km: z.number().int(),
  interval_months: z.number().int(),
  description: z.string().nullable(),
  source_document: z.string().nullable(),
})
export type ComplianceRule = z.infer<typeof complianceRuleSchema>

export const complianceRuleCreateSchema = z
  .object({
    vehicle_make: z.string().min(1),
    vehicle_model: z.string().min(1),
    service_type: serviceTypeSchema,
    interval_km: z.number().int().positive(),
    interval_months: z.number().int().positive(),
    description: z.string().optional(),
    source_document: z.string().optional(),
  })
  .strict()
export type ComplianceRuleCreate = z.infer<typeof complianceRuleCreateSchema>

// vehicle_make/vehicle_model/service_type form the composite lookup key and
// are not editable — changing them would silently reassign which vehicles
// the rule applies to (see the backend docstring).
export const complianceRuleUpdateSchema = z
  .object({
    interval_km: z.number().int().positive().optional(),
    interval_months: z.number().int().positive().optional(),
    description: z.string().optional(),
    source_document: z.string().optional(),
  })
  .strict()
export type ComplianceRuleUpdate = z.infer<typeof complianceRuleUpdateSchema>

export const complianceRuleListParamsSchema = z.object({
  make: z.string().optional(),
  model: z.string().optional(),
  service_type: serviceTypeSchema.optional(),
})
export type ComplianceRuleListParams = z.infer<typeof complianceRuleListParamsSchema>

export const complianceStatusItemSchema = z.object({
  rule: complianceRuleSchema,
  status: complianceStatusSchema,
  km_remaining: z.number().int().nullable(),
  days_remaining: z.number().int().nullable(),
  last_service_date: dateStringSchema.nullable(),
})
export type ComplianceStatusItem = z.infer<typeof complianceStatusItemSchema>

export const vehicleComplianceResponseSchema = z.object({
  vehicle_id: uuidSchema,
  items: z.array(complianceStatusItemSchema),
})
export type VehicleComplianceResponse = z.infer<typeof vehicleComplianceResponseSchema>

export const fleetComplianceMatrixResponseSchema = z.array(vehicleComplianceResponseSchema)
export type FleetComplianceMatrixResponse = z.infer<typeof fleetComplianceMatrixResponseSchema>
