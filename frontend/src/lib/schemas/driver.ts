import { z } from "zod"
import { dateStringSchema, uuidSchema } from "./common"
import { driverStatusSchema } from "./enums"

// Mirrors backend/app/schemas/driver.py.

export const driverSchema = z.object({
  id: uuidSchema,
  organization_id: uuidSchema,
  user_id: uuidSchema.nullable(),
  full_name: z.string(),
  license_number: z.string(),
  license_expiry: dateStringSchema,
  phone: z.string(),
  status: driverStatusSchema,
  license_type: z.string().nullable(),
  license_issue_date: dateStringSchema.nullable(),
  license_current_status: z.string().nullable(),
})
export type Driver = z.infer<typeof driverSchema>

export const driverCreateSchema = z
  .object({
    full_name: z.string().min(1),
    license_number: z.string().min(1),
    license_expiry: dateStringSchema,
    phone: z.string().min(1),
    status: driverStatusSchema.default("active"),
    license_type: z.string().optional(),
    license_issue_date: dateStringSchema.optional(),
    license_current_status: z.string().optional(),
    // Links an existing User to this Driver profile; settable only by A/FM
    // (enforced by backend RBAC, not this schema).
    user_id: uuidSchema.optional(),
  })
  .strict()
export type DriverCreate = z.infer<typeof driverCreateSchema>

export const driverUpdateSchema = z
  .object({
    full_name: z.string().min(1).optional(),
    license_number: z.string().min(1).optional(),
    license_expiry: dateStringSchema.optional(),
    phone: z.string().min(1).optional(),
    status: driverStatusSchema.optional(),
    license_type: z.string().optional(),
    license_issue_date: dateStringSchema.optional(),
    license_current_status: z.string().optional(),
    user_id: uuidSchema.optional(),
  })
  .strict()
export type DriverUpdate = z.infer<typeof driverUpdateSchema>
