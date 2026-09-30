import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { z } from "zod"
import { documentKeys } from "@/lib/query/keys"
import {
  documentChunkSchema,
  documentResponseSchema,
  documentSearchResponseSchema,
  type DocumentChunk,
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

// A document's stored passages in reading order, for the preview. Empty until it is ready.
export function getDocumentChunks(id: string): Promise<DocumentChunk[]> {
  return apiRequest(`/documents/${id}/chunks`, { schema: z.array(documentChunkSchema) })
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
export function useDocuments(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: documentKeys.list(),
    queryFn: listDocuments,
    enabled: options.enabled ?? true,
    refetchInterval: (query) => (query.state.data?.some((d) => d.status === "processing") ? DOCUMENT_POLL_MS : false),
  })
}

// The passages shown in the document preview; fetched only while the preview is open.
export function useDocumentChunks(id: string, enabled: boolean) {
  return useQuery({ queryKey: documentKeys.chunks(id), queryFn: () => getDocumentChunks(id), enabled })
}

export const DOCUMENT_READY_POLL_MS = 1500
export const DOCUMENT_READY_TIMEOUT_MS = 120_000

// Resolves with the document once it is `ready`; rejects if it `failed`, the wait times out, or `signal` aborts.
// Ingestion (extraction, table summaries, embedding) runs in the background after an upload is accepted, and a chat
// turn can only search a document that has finished, so the chat waits here before sending its message.
export async function waitForDocumentReady(
  id: string,
  options: { signal?: AbortSignal; intervalMs?: number; timeoutMs?: number; onStatus?: (doc: DocumentResponse) => void } = {}
): Promise<DocumentResponse> {
  const { signal, intervalMs = DOCUMENT_READY_POLL_MS, timeoutMs = DOCUMENT_READY_TIMEOUT_MS, onStatus } = options
  const deadline = Date.now() + timeoutMs
  for (;;) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError")
    const doc = await getDocument(id)
    onStatus?.(doc)
    if (doc.status === "ready") return doc
    if (doc.status === "failed") throw new Error(doc.error_message ?? "The document couldn't be processed.")
    if (Date.now() + intervalMs > deadline) throw new Error("The document is taking too long to process. Try again in a moment.")
    await new Promise<void>((resolve) => setTimeout(resolve, intervalMs))
  }
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
