import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { z } from "zod"
import { apiRequest } from "@/lib/api/client"

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init,
  })
}

describe("apiRequest", () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("prefixes /api/proxy and parses the body with the given schema", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: "abc" }))
    const schema = z.object({ id: z.string() })

    const result = await apiRequest("/vehicles/abc", { schema })

    expect(result).toEqual({ id: "abc" })
    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/proxy/vehicles/abc")
  })

  it("serializes query params and skips undefined values", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]))
    await apiRequest("/fuel", {
      query: { vehicle_id: "v1", driver_id: undefined, limit: 50 },
      schema: z.array(z.unknown()),
    })

    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/proxy/fuel?vehicle_id=v1&limit=50")
  })

  it("returns undefined on a 204 with no schema, without touching the body", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }))
    const result = await apiRequest("/vehicles/abc", { method: "DELETE" })
    expect(result).toBeUndefined()
  })

  it("throws a schema error when the response doesn't match, and never returns unvalidated data", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ wrong: "shape" }))
    const schema = z.object({ id: z.string() })

    await expect(apiRequest("/vehicles/abc", { schema })).rejects.toMatchObject({ kind: "schema" })
  })

  it("maps a non-ok response through the error mapper", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "Vehicle not found" }, { status: 404 }))
    await expect(apiRequest("/vehicles/missing", { schema: z.unknown() })).rejects.toMatchObject({
      kind: "not_found",
      status: 404,
      message: "Vehicle not found",
    })
  })

  it("throws a network error when fetch itself rejects", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"))
    await expect(apiRequest("/vehicles", { schema: z.unknown() })).rejects.toEqual({ kind: "network" })
  })

  it("sets a JSON content-type for a plain body but leaves FormData untouched", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }))
    await apiRequest("/vehicles", { method: "POST", body: { make: "Toyota" }, schema: z.unknown() })
    const [, jsonInit] = fetchMock.mock.calls[0]
    expect(jsonInit.headers["Content-Type"]).toBe("application/json")
    expect(jsonInit.body).toBe(JSON.stringify({ make: "Toyota" }))

    fetchMock.mockClear()
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }))
    const formData = new FormData()
    formData.append("file", new File(["x"], "receipt.pdf"))
    await apiRequest("/fuel/1/receipt", { method: "POST", body: formData, schema: z.unknown() })
    const [, formInit] = fetchMock.mock.calls[0]
    expect(formInit.headers["Content-Type"]).toBeUndefined()
    expect(formInit.body).toBe(formData)
  })

  it("sends credentials same-origin so the httpOnly session cookie is included", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }))
    await apiRequest("/vehicles", { schema: z.unknown() })
    const [, init] = fetchMock.mock.calls[0]
    expect(init.credentials).toBe("same-origin")
  })
})
