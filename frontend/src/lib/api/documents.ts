import { unavailable, type Unavailable } from "./not-implemented"
import type { DocumentResponse, DocumentSearchRequest, DocumentSearchResponse } from "@/lib/schemas/document"

// `/documents` doesn't exist on this backend — it lives only on the
// `backend` branch, which plans/07's 2026-09-29 constraint says is never
// merged into `frontend`. Every function here is a typed stub: same
// signature the real adapter would have, but each always resolves to
// `{ status: "unavailable" }` with no fetch call anywhere in this file.
// The types (DocumentResponse etc.) are the target contract, kept so the
// Library/upload/citation components below have something real to type
// their props against in tests.

export function listDocuments(): Promise<Unavailable> {
  return unavailable()
}

export function getDocument(id: string): Promise<Unavailable> {
  void id
  return unavailable()
}

export function uploadDocument(input: { file: File; document_type: string; vehicle_id?: string }): Promise<Unavailable> {
  void input
  return unavailable()
}

export function deleteDocument(id: string): Promise<Unavailable> {
  void id
  return unavailable()
}

export function searchDocuments(input: DocumentSearchRequest): Promise<Unavailable> {
  void input
  return unavailable()
}

// Re-exported so a future real adapter (and tests today) can import the
// target shapes from this one module rather than reaching into lib/schemas.
export type { DocumentResponse, DocumentSearchRequest, DocumentSearchResponse }
