import { DOCUMENT_TYPE_LABELS } from "@/lib/enum-labels"
import type { DocumentType } from "@/lib/schemas/enums"

export const DOCUMENT_UPLOAD_MAX_BYTES = 20 * 1024 * 1024 // the backend's RAG_MAX_UPLOAD_MB
export const PDF_MIME_TYPE = "application/pdf"

// Mirrors the backend: admins may upload every type, fleet managers all but "legal", everyone else none.
// (The backend's 403 is the enforcement; this only decides what the UI offers.)
export function uploadableDocumentTypes(role: string | null | undefined): DocumentType[] {
  const all = Object.keys(DOCUMENT_TYPE_LABELS) as DocumentType[]
  if (role === "admin") return all
  if (role === "fleet_manager") return all.filter((t) => t !== "legal")
  return []
}

export function isPdf(file: File): boolean {
  return file.type === PDF_MIME_TYPE || (file.type === "" && file.name.toLowerCase().endsWith(".pdf"))
}
