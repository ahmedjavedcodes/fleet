import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { z } from "zod"
import { apiRequestPage, type Page } from "@/lib/api/client"
import { nextOffset } from "@/lib/api/paging"

const page = (n: number, total: number | null): Page<number[]> => ({ items: Array.from({ length: n }, (_, i) => i), total })

describe("nextOffset", () => {
  it("continues from what is loaded until the reported total is reached", () => {
    expect(nextOffset([page(25, 60)], page(25, 60), 25)).toBe(25)
    expect(nextOffset([page(25, 60), page(25, 60)], page(25, 60), 25)).toBe(50)
    expect(nextOffset([page(25, 60), page(25, 60), page(10, 60)], page(10, 60), 25)).toBeUndefined()
  })

  it("stops exactly at the total even when the last page is full", () => {
    expect(nextOffset([page(25, 50), page(25, 50)], page(25, 50), 25)).toBeUndefined()
  })

  it("stops on an empty page", () => {
    expect(nextOffset([page(25, 100), page(0, 100)], page(0, 100), 25)).toBeUndefined()
  })

  it("without a total, a full page means there may be more and a short one means the end", () => {
    expect(nextOffset([page(25, null)], page(25, null), 25)).toBe(25)
    expect(nextOffset([page(25, null), page(7, null)], page(7, null), 25)).toBeUndefined()
  })
})

describe("apiRequestPage", () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  it("returns the validated page and the total from X-Total-Count", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify([1, 2]), { status: 200, headers: { "X-Total-Count": "486" } }))

    const result = await apiRequestPage("/dashboard/fleet-health", { query: { limit: 25, offset: 0 }, schema: z.array(z.number()) })

    expect(result).toEqual({ items: [1, 2], total: 486 })
    expect(fetchMock.mock.calls[0][0]).toBe("/api/proxy/dashboard/fleet-health?limit=25&offset=0")
  })

  it("reports a missing or malformed header as an unknown total", async () => {
    fetchMock.mockResolvedValueOnce(new Response("[]", { status: 200 }))
    fetchMock.mockResolvedValueOnce(new Response("[]", { status: 200, headers: { "X-Total-Count": "lots" } }))

    expect((await apiRequestPage("/x", { schema: z.array(z.number()) })).total).toBeNull()
    expect((await apiRequestPage("/x", { schema: z.array(z.number()) })).total).toBeNull()
  })

  it("rejects a body that does not match the schema, like apiRequest", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify(["no"]), { status: 200 }))
    await expect(apiRequestPage("/x", { schema: z.array(z.number()) })).rejects.toBeTruthy()
  })
})
