import { z } from "zod"
import { decimalStringSchema, uuidSchema } from "./common"

// Mirrors backend/app/schemas/inventory.py PartsInventory*.

export const compatibleVehicleSchema = z.object({
  make: z.string(),
  model: z.string(),
})
export type CompatibleVehicle = z.infer<typeof compatibleVehicleSchema>

export const partsInventorySchema = z.object({
  id: uuidSchema,
  organization_id: uuidSchema,
  part_number: z.string(),
  name: z.string(),
  category: z.string().nullable(),
  compatible_vehicles: z.array(compatibleVehicleSchema),
  reorder_threshold: z.number().int(),
  unit_cost: decimalStringSchema,
  supplier_id: uuidSchema.nullable(),
  qty_on_hand: z.number().int(),
})
export type PartsInventory = z.infer<typeof partsInventorySchema>

export const lowStockResponseSchema = partsInventorySchema.extend({
  deficit: z.number().int(),
})
export type LowStockResponse = z.infer<typeof lowStockResponseSchema>

export const partsInventoryCreateSchema = z
  .object({
    part_number: z.string().min(1),
    name: z.string().min(1),
    category: z.string().optional(),
    compatible_vehicles: z.array(compatibleVehicleSchema).default([]),
    reorder_threshold: z.number().int().min(0),
    unit_cost: z.number().positive(),
    supplier_id: uuidSchema.optional(),
    qty_on_hand: z.number().int().min(0).default(0),
  })
  .strict()
export type PartsInventoryCreate = z.infer<typeof partsInventoryCreateSchema>

export const partsInventoryUpdateSchema = z
  .object({
    part_number: z.string().min(1).optional(),
    name: z.string().min(1).optional(),
    category: z.string().optional(),
    compatible_vehicles: z.array(compatibleVehicleSchema).optional(),
    reorder_threshold: z.number().int().min(0).optional(),
    unit_cost: z.number().positive().optional(),
    supplier_id: uuidSchema.optional(),
    // The one direct write path to qty_on_hand for a manual adjustment; every
    // other mutation goes through the backend's receive/decrement flows.
    qty_on_hand: z.number().int().min(0).optional(),
  })
  .strict()
export type PartsInventoryUpdate = z.infer<typeof partsInventoryUpdateSchema>

export const partsInventoryListParamsSchema = z.object({
  category: z.string().optional(),
  supplier_id: uuidSchema.optional(),
  compatible_make: z.string().optional(),
  compatible_model: z.string().optional(),
})
export type PartsInventoryListParams = z.infer<typeof partsInventoryListParamsSchema>
