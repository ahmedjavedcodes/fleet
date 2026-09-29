import { z } from "zod"
import { decimalStringSchema, uuidSchema } from "./common"
import { supplierCategorySchema } from "./enums"

// Mirrors backend/app/schemas/supplier.py.

export const supplierSchema = z.object({
  id: uuidSchema,
  organization_id: uuidSchema,
  name: z.string(),
  contact_email: z.string().nullable(),
  phone: z.string().nullable(),
  avg_lead_time_days: z.number().int().nullable(),
  address: z.string().nullable(),
  category: supplierCategorySchema,
  // Computed by the backend — never accepted on create/update.
  reliability_score: decimalStringSchema.nullable(),
})
export type Supplier = z.infer<typeof supplierSchema>

export const supplierCreateSchema = z
  .object({
    name: z.string().min(1, "Name is required"),
    contact_email: z.string().email().optional(),
    phone: z.string().min(1).optional(),
    avg_lead_time_days: z.number().int().positive().optional(),
    address: z.string().min(1).optional(),
    category: supplierCategorySchema.default("other"),
  })
  .strict()
export type SupplierCreate = z.infer<typeof supplierCreateSchema>

export const supplierUpdateSchema = z
  .object({
    name: z.string().min(1).optional(),
    contact_email: z.string().email().optional(),
    phone: z.string().min(1).optional(),
    avg_lead_time_days: z.number().int().positive().optional(),
    address: z.string().min(1).optional(),
    category: supplierCategorySchema.optional(),
  })
  .strict()
export type SupplierUpdate = z.infer<typeof supplierUpdateSchema>
