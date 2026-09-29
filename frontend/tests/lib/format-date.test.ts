import { describe, expect, it } from "vitest"
import { formatDate, formatDateTime, formatDurationBetween, formatMonthLabel } from "@/lib/format-date"

describe("formatMonthLabel", () => {
  it("formats a YYYY-MM dashboard month point", () => {
    expect(formatMonthLabel("2026-06")).toBe("Jun 26")
    expect(formatMonthLabel("2026-01")).toBe("Jan 26")
  })
})

describe("formatDate", () => {
  it("formats a YYYY-MM-DD date string", () => {
    expect(formatDate("2026-06-12")).toBe("12 Jun 2026")
  })
})

describe("formatDateTime", () => {
  it("includes both date and time", () => {
    const result = formatDateTime("2026-06-12T14:05:00Z")
    expect(result).toContain("12 Jun 2026")
  })
})

describe("formatDurationBetween", () => {
  it("formats hours and minutes", () => {
    expect(formatDurationBetween("2026-06-12T08:00:00Z", "2026-06-12T10:15:00Z")).toBe("2h 15m")
  })

  it("omits minutes when exactly on the hour", () => {
    expect(formatDurationBetween("2026-06-12T08:00:00Z", "2026-06-12T10:00:00Z")).toBe("2h")
  })

  it("omits hours when under 60 minutes", () => {
    expect(formatDurationBetween("2026-06-12T08:00:00Z", "2026-06-12T08:45:00Z")).toBe("45m")
  })

  it("never goes negative for an out-of-order pair", () => {
    expect(formatDurationBetween("2026-06-12T10:00:00Z", "2026-06-12T08:00:00Z")).toBe("0m")
  })
})
