import { z } from "zod"
import { dateTimeStringSchema, uuidSchema } from "./common"
import { documentStatusSchema, documentTypeSchema } from "./enums"

// Mirrors backend/app/schemas/document.py (the /api/v1/documents contract).

export const documentResponseSchema = z.object({
  id: uuidSchema,
  filename: z.string(),
  document_type: documentTypeSchema,
  vehicle_id: uuidSchema.nullable(),
  status: documentStatusSchema,
  version: z.number().int(),
  size_bytes: z.number().int(),
  chunk_count: z.number().int().nullable(),
  tables_found: z.number().int().nullable(),
  tables_summarized: z.number().int().nullable(),
  error_message: z.string().nullable(),
  created_at: dateTimeStringSchema,
  updated_at: dateTimeStringSchema,
})
export type DocumentResponse = z.infer<typeof documentResponseSchema>

export const documentSearchRequestSchema = z.object({
  query: z.string().min(3).max(500),
  document_types: z.array(documentTypeSchema).optional(),
})
export type DocumentSearchRequest = z.infer<typeof documentSearchRequestSchema>

export const documentSearchHitSchema = z.object({
  document_id: uuidSchema,
  filename: z.string(),
  document_type: documentTypeSchema,
  chunk_index: z.number().int(),
  text: z.string(),
  relevance: z.number().min(0).max(1),
})
export type DocumentSearchHit = z.infer<typeof documentSearchHitSchema>

export const documentSearchResponseSchema = z.object({
  results: z.array(documentSearchHitSchema).max(3),
  cached: z.boolean(),
})
export type DocumentSearchResponse = z.infer<typeof documentSearchResponseSchema>
