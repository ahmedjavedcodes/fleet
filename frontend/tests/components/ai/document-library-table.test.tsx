import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { DocumentLibraryTable } from "@/components/ai/document-library-table"
import type { DocumentResponse } from "@/lib/schemas/document"

const DOC: DocumentResponse = {
  id: "d1",
  filename: "fleet-policy.pdf",
  document_type: "policy",
  vehicle_id: null,
  status: "ready",
  version: 2,
  size_bytes: 1_500_000,
  chunk_count: 12,
  tables_found: 1,
  tables_summarized: 1,
  error_message: null,
  created_at: "2026-06-01T10:00:00Z",
  updated_at: "2026-06-02T10:00:00Z",
}

describe("DocumentLibraryTable", () => {
  it("renders filename, type, version and a formatted size", () => {
    render(<DocumentLibraryTable documents={[DOC]} />)
    expect(screen.getByText("fleet-policy.pdf")).toBeInTheDocument()
    expect(screen.getByText("Policy")).toBeInTheDocument()
    expect(screen.getByText("v2")).toBeInTheDocument()
    expect(screen.getByText("1.4 MB")).toBeInTheDocument()
  })

  it("shows an animated processing pill for a processing document", () => {
    render(<DocumentLibraryTable documents={[{ ...DOC, status: "processing" }]} />)
    expect(screen.getByText("Processing")).toBeInTheDocument()
  })

  it("only renders a delete action when canDelete is true, and calls onDelete with the row", () => {
    const onDelete = vi.fn()
    const { rerender } = render(<DocumentLibraryTable documents={[DOC]} />)
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument()

    rerender(<DocumentLibraryTable documents={[DOC]} canDelete onDelete={onDelete} />)
    screen.getByRole("button", { name: "Delete" }).click()
    expect(onDelete).toHaveBeenCalledWith(DOC)
  })
})
