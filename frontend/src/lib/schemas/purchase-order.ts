import { z } from "zod"
import { dateStringSchema, decimalStringSchema, uuidSchema } from "./common"
import { purchaseOrderStatusSchema } from "./enums"

// Mirrors backend/app/schemas/inventory.py PurchaseOrder*.

export const purchaseOrderLineItemSchema = z.object({
  part_id: uuidSchema,
  qty: z.number().int().positive(),
  unit_price: decimalStringSchema,
})
export type PurchaseOrderLineItem = z.infer<typeof purchaseOrderLineItemSchema>

export const purchaseOrderSchema = z.object({
  id: uuidSchema,
  organization_id: uuidSchema,
  supplier_id: uuidSchema,
  order_date: dateStringSchema,
  expected_delivery: dateStringSchema,
  actual_delivery: dateStringSchema.nullable(),
  status: purchaseOrderStatusSchema,
  total_cost: decimalStringSchema,
  line_items: z.array(purchaseOrderLineItemSchema),
})
export type PurchaseOrder = z.infer<typeof purchaseOrderSchema>

// The request-side line item takes a plain number for unit_price (the
// backend accepts a JSON number for Decimal-typed request fields; only
// *responses* serialize Decimal as a string).
const purchaseOrderLineItemInputSchema = z.object({
  part_id: uuidSchema,
  qty: z.number().int().positive(),
  unit_price: z.number().positive(),
})

export const purchaseOrderCreateSchema = z
  .object({
    supplier_id: uuidSchema,
    order_date: dateStringSchema,
    expected_delivery: dateStringSchema,
    line_items: z.array(purchaseOrderLineItemInputSchema).min(1, "Add at least one line item"),
  })
  .strict()
export type PurchaseOrderCreate = z.infer<typeof purchaseOrderCreateSchema>

// Only pre-receive fields are editable — receiving happens exclusively
// through the dedicated /receive endpoint (purchaseOrderReceive below).
export const purchaseOrderUpdateSchema = z
  .object({
    expected_delivery: dateStringSchema.optional(),
    line_items: z.array(purchaseOrderLineItemInputSchema).optional(),
    status: purchaseOrderStatusSchema.optional(),
  })
  .strict()
export type PurchaseOrderUpdate = z.infer<typeof purchaseOrderUpdateSchema>

export const purchaseOrderListParamsSchema = z.object({
  status: purchaseOrderStatusSchema.optional(),
  supplier_id: uuidSchema.optional(),
  date_from: dateStringSchema.optional(),
  date_to: dateStringSchema.optional(),
})
export type PurchaseOrderListParams = z.infer<typeof purchaseOrderListParamsSchema>

export const stockUpdateSchema = z.object({
  part_id: uuidSchema,
  new_qty: z.number().int(),
})
export type StockUpdate = z.infer<typeof stockUpdateSchema>

export const purchaseOrderReceiveResponseSchema = z.object({
  order: purchaseOrderSchema,
  stock_updates: z.array(stockUpdateSchema),
})
export type PurchaseOrderReceiveResponse = z.infer<typeof purchaseOrderReceiveResponseSchema>
