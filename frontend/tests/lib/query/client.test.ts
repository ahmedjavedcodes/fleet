import { describe, expect, it } from "vitest"
import { makeQueryClient } from "@/lib/query/client"

describe("makeQueryClient", () => {
  it("applies the CLAUDE.md §5.1 defaults", () => {
    const queries = makeQueryClient().getDefaultOptions().queries
    expect(queries?.staleTime).toBe(30_000)
    expect(queries?.refetchOnWindowFocus).toBe(true)
  })

  it("creates an independent client per call", () => {
    expect(makeQueryClient()).not.toBe(makeQueryClient())
  })
})
