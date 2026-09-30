import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { z } from "zod"
import { documentKeys } from "@/lib/query/keys"
import {
  documentResponseSchema,
  documentSearchResponseSchema,
  type DocumentResponse,
  type DocumentSearchRequest,
  type DocumentSearchResponse,
} from "@/lib/schemas/document"
import type { DocumentType } from "@/lib/schemas/enums"
import { apiRequest } from "./client"

// --- Reads -------------------------------------------------------------

// The backend already limits the list to the document types the caller's role
// may see, so the page never filters by role itself.
export function listDocuments(): Promise<DocumentResponse[]> {
  return apiRequest("/documents", { schema: z.array(documentResponseSchema) })
}

export function getDocument(id: string): Promise<DocumentResponse> {
  return apiRequest(`/documents/${id}`, { schema: documentResponseSchema })
}

// Semantic search over the caller's role-visible documents. An empty
// `results` array is a normal answer (nothing cleared the reranker), not an error.
export function searchDocuments(input: DocumentSearchRequest): Promise<DocumentSearchResponse> {
  return apiRequest("/documents/search", { method: "POST", body: input, schema: documentSearchResponseSchema })
}

// --- Writes (A/FM only) --------------------------------------------------

// Multipart. Resolves as soon as the file is accepted (202, status
// "processing"); extraction, table summarising and embedding continue in the
// background, so callers poll the list until the document is ready or failed.
// Re-uploading the same filename + type replaces the earlier version.
export function uploadDocument(input: { file: File; document_type: DocumentType; vehicle_id?: string }): Promise<DocumentResponse> {
  const formData = new FormData()
  formData.append("file", input.file)
  formData.append("document_type", input.document_type)
  if (input.vehicle_id) formData.append("vehicle_id", input.vehicle_id)
  return apiRequest("/documents/upload", { method: "POST", body: formData, schema: documentResponseSchema })
}

export function deleteDocument(id: string): Promise<void> {
  return apiRequest(`/documents/${id}`, { method: "DELETE" })
}

// --- Hooks -------------------------------------------------------------

export const DOCUMENT_POLL_MS = 3000

// Polls while any document is still processing, and stops on its own once
// everything has settled — no timer to manage in the page.
export function useDocuments() {
  return useQuery({
    queryKey: documentKeys.list(),
    queryFn: listDocuments,
    refetchInterval: (query) => (query.state.data?.some((d) => d.status === "processing") ? DOCUMENT_POLL_MS : false),
  })
}

export function useUploadDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: uploadDocument,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: documentKeys.all }),
  })
}

export function useDeleteDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteDocument,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: documentKeys.all }),
  })
}

export function useSearchDocuments() {
  return useMutation({ mutationFn: searchDocuments })
}

export type { DocumentResponse, DocumentSearchRequest, DocumentSearchResponse }
