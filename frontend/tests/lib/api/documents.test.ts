import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  deleteDocument,
  getDocument,
  getDocumentChunks,
  listDocuments,
  searchDocuments,
  uploadDocument,
  waitForDocumentReady,
} from "@/lib/api/documents"

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

  it("reads a document's passages from /documents/{id}/chunks", async () => {
    fetchMock.mockResolvedValue(jsonResponse([{ chunk_index: 0, text: "2.0 Incident\nReport within 1 hour." }]))

    await expect(getDocumentChunks(DOC.id)).resolves.toEqual([{ chunk_index: 0, text: "2.0 Incident\nReport within 1 hour." }])
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/proxy/documents/${DOC.id}/chunks`)
  })

  it("rejects chunks that don't match the contract", async () => {
    fetchMock.mockResolvedValue(jsonResponse([{ chunk_index: "zero", text: 5 }]))

    await expect(getDocumentChunks(DOC.id)).rejects.toThrow()
  })

  it("restricts a search to the given documents", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ results: [], cached: false }))

    await searchDocuments({ query: "tyre pressure", document_ids: [DOC.id] })

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ query: "tyre pressure", document_ids: [DOC.id] })
  })
})

describe("waitForDocumentReady", () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  it("polls until the document is ready, reporting each status", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(DOC))
      .mockResolvedValueOnce(jsonResponse(DOC))
      .mockResolvedValueOnce(jsonResponse({ ...DOC, status: "ready", chunk_count: 9 }))
    const seen: string[] = []

    const doc = await waitForDocumentReady(DOC.id, { intervalMs: 1, onStatus: (d) => seen.push(d.status) })

    expect(doc.status).toBe("ready")
    expect(seen).toEqual(["processing", "processing", "ready"])
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it("rejects with the reason when processing failed", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ...DOC, status: "failed", error_message: "no extractable text (scanned PDFs are not supported)" }))

    await expect(waitForDocumentReady(DOC.id, { intervalMs: 1 })).rejects.toThrow("no extractable text")
  })

  it("gives up with a clear message instead of polling forever", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse(DOC))) // a Response body can only be read once

    await expect(waitForDocumentReady(DOC.id, { intervalMs: 5, timeoutMs: 12 })).rejects.toThrow("taking too long")
  })

  it("stops as soon as it is aborted", async () => {
    fetchMock.mockResolvedValue(jsonResponse(DOC))
    const controller = new AbortController()
    controller.abort()

    await expect(waitForDocumentReady(DOC.id, { signal: controller.signal, intervalMs: 1 })).rejects.toThrow("Aborted")
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
