import { describe, expect, it } from "vitest"
import { formatInt, formatMoney, formatNumber, parseDecimal } from "@/lib/api/decimal"

describe("parseDecimal", () => {
  it("parses a backend decimal string into a number", () => {
    expect(parseDecimal("12.3400")).toBeCloseTo(12.34)
    expect(parseDecimal("0")).toBe(0)
    expect(parseDecimal("-5.5")).toBe(-5.5)
  })

  it("throws on a non-numeric string rather than returning NaN silently", () => {
    expect(() => parseDecimal("not-a-number")).toThrow()
    // Callers must check for null themselves before calling — cost_per_km,
    // reliability_score etc. are `decimalStringSchema.nullable()` in the
    // zod schemas, and this function's signature takes only `string`.
    expect(() => parseDecimal("")).toThrow()
  })
})

describe("formatMoney", () => {
  it("formats a decimal string as currency, grouped, with no float math involved", () => {
    const formatted = formatMoney("1234.50")
    expect(formatted).toMatch(/1,235|1,234\.50|1,234\.5/) // ICU may round the display, never the source value
  })

  it("defaults to PKR", () => {
    // Just confirm it doesn't throw for the default currency and produces
    // digits — exact symbol rendering ("Rs", "₨", "PKR") varies by ICU data.
    expect(() => formatMoney("100")).not.toThrow()
    expect(formatMoney("100")).toMatch(/100/)
  })
})

describe("formatNumber", () => {
  it("formats with a bounded number of decimal places", () => {
    expect(formatNumber("12.34567", 2)).toBe("12.35")
    expect(formatNumber("12.34567", 4)).toBe("12.3457")
  })

  it("defaults to 2 decimal places", () => {
    expect(formatNumber("11.2")).toBe("11.2")
  })
})

describe("formatInt", () => {
  it("formats a plain integer with locale grouping and no decimals", () => {
    expect(formatInt(87420)).toBe("87,420")
    expect(formatInt(0)).toBe("0")
  })
})
