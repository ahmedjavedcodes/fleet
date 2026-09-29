import { describe, expect, it } from "vitest"
import { deleteDocument, getDocument, listDocuments, searchDocuments, uploadDocument } from "@/lib/api/documents"

describe("lib/api/documents", () => {
  it("every function resolves to { status: 'unavailable' } regardless of input", async () => {
    await expect(listDocuments()).resolves.toEqual({ status: "unavailable" })
    await expect(getDocument("doc-1")).resolves.toEqual({ status: "unavailable" })
    await expect(deleteDocument("doc-1")).resolves.toEqual({ status: "unavailable" })
    await expect(searchDocuments({ query: "brake pads" })).resolves.toEqual({ status: "unavailable" })
    await expect(uploadDocument({ file: new File(["x"], "manual.pdf"), document_type: "manual" })).resolves.toEqual({
      status: "unavailable",
    })
  })
})
