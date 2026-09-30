import { describe, expect, it } from "vitest"
import { distinctOptions, inDateRange, matchesSearch } from "@/lib/table-filters"

describe("matchesSearch", () => {
  it("matches everything for a blank query", () => {
    expect(matchesSearch("", "AB-1234")).toBe(true)
    expect(matchesSearch("   ", null)).toBe(true)
  })

  it("is case-insensitive and matches substrings in any field", () => {
    expect(matchesSearch("hilux", "AB-1234", "Toyota Hilux")).toBe(true)
    expect(matchesSearch("ab-12", "AB-1234")).toBe(true)
    expect(matchesSearch("ford", "AB-1234", "Toyota Hilux")).toBe(false)
  })

  it("requires every term to match, across different fields", () => {
    expect(matchesSearch("ab-1234 ali", "AB-1234", "Ali Khan")).toBe(true)
    expect(matchesSearch("ab-1234 bilal", "AB-1234", "Ali Khan")).toBe(false)
  })

  it("ignores null and undefined fields instead of throwing", () => {
    expect(matchesSearch("ali", null, undefined, "Ali Khan")).toBe(true)
    expect(matchesSearch("ali", null, undefined)).toBe(false)
  })
})

describe("inDateRange", () => {
  it("treats both bounds as inclusive", () => {
    expect(inDateRange("2026-09-29", "2026-09-29", "2026-09-29")).toBe(true)
    expect(inDateRange("2026-09-28", "2026-09-29", "2026-09-30")).toBe(false)
    expect(inDateRange("2026-10-01", "2026-09-29", "2026-09-30")).toBe(false)
  })

  it("compares the date part of an ISO timestamp", () => {
    expect(inDateRange("2026-09-30T23:59:00Z", "", "2026-09-30")).toBe(true)
    expect(inDateRange("2026-09-30T08:00:00Z", "2026-09-30", "")).toBe(true)
  })

  it("leaves an empty bound open-ended", () => {
    expect(inDateRange("2020-01-01", "", "")).toBe(true)
    expect(inDateRange("2020-01-01", "2026-01-01", "")).toBe(false)
    expect(inDateRange("2030-01-01", "", "2026-01-01")).toBe(false)
  })
})

describe("distinctOptions", () => {
  it("returns sorted unique non-empty values as options", () => {
    expect(distinctOptions(["Renewal Pending", "Active", null, "Active", "", undefined])).toEqual([
      { value: "Active", label: "Active" },
      { value: "Renewal Pending", label: "Renewal Pending" },
    ])
  })
})
