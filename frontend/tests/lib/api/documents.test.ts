import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { deleteDocument, getDocument, listDocuments, searchDocuments, uploadDocument } from "@/lib/api/documents"

const DOC = {
  id: "8f6c1d7e-3b0a-4a51-9d6e-0a1b2c3d4e5f",
  filename: "hilux-manual.pdf",
  document_type: "manual",
  vehicle_id: null,
  status: "processing",
  version: 1,
  size_bytes: 2048,
  chunk_count: 0,
  tables_found: 0,
  tables_summarized: 0,
  error_message: null,
  created_at: "2026-09-30T08:00:00Z",
  updated_at: "2026-09-30T08:00:00Z",
}

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" }, ...init })
}

describe("lib/api/documents", () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  it("lists documents from /documents and validates each against the schema", async () => {
    fetchMock.mockResolvedValue(jsonResponse([DOC]))
    await expect(listDocuments()).resolves.toEqual([DOC])
    expect(fetchMock.mock.calls[0][0]).toBe("/api/proxy/documents")
  })

  it("rejects a list item that doesn't match the contract", async () => {
    fetchMock.mockResolvedValue(jsonResponse([{ ...DOC, status: "queued" }]))
    await expect(listDocuments()).rejects.toBeDefined()
  })

  it("gets one document by id", async () => {
    fetchMock.mockResolvedValue(jsonResponse(DOC))
    await getDocument(DOC.id)
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/proxy/documents/${DOC.id}`)
  })

  it("uploads as multipart with file, type and optional vehicle", async () => {
    fetchMock.mockResolvedValue(jsonResponse(DOC, { status: 202 }))
    const file = new File(["x"], "hilux-manual.pdf", { type: "application/pdf" })

    await uploadDocument({ file, document_type: "manual", vehicle_id: "veh-1" })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/proxy/documents/upload")
    expect(init.method).toBe("POST")
    const form = init.body as FormData
    expect(form.get("file")).toBeInstanceOf(File)
    expect(form.get("document_type")).toBe("manual")
    expect(form.get("vehicle_id")).toBe("veh-1")
    // The browser must set the multipart boundary itself.
    expect(init.headers["Content-Type"]).toBeUndefined()
  })

  it("omits vehicle_id from the upload when none is chosen", async () => {
    fetchMock.mockResolvedValue(jsonResponse(DOC, { status: 202 }))
    await uploadDocument({ file: new File(["x"], "a.pdf"), document_type: "policy" })
    expect((fetchMock.mock.calls[0][1].body as FormData).has("vehicle_id")).toBe(false)
  })

  it("deletes by id and accepts the empty 204 response", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    await expect(deleteDocument(DOC.id)).resolves.toBeUndefined()
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`/api/proxy/documents/${DOC.id}`)
    expect(init.method).toBe("DELETE")
  })

  it("posts a search and returns hits, treating an empty result as a valid answer", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ results: [], cached: false }))
    await expect(searchDocuments({ query: "brake pads" })).resolves.toEqual({ results: [], cached: false })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/proxy/documents/search")
    expect(JSON.parse(init.body)).toEqual({ query: "brake pads" })
  })
})
