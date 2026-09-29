// Backend Decimal fields (costs, liters, cost_per_km, reliability_score, …)
// arrive as JSON strings, e.g. "12.3400" (CLAUDE.md §7). This is the single
// helper that converts them for display — never do float math on money by
// parsing ad hoc elsewhere, and never sum totals client-side (the backend
// supplies every total it wants shown).

/**
 * Parses a backend decimal string into a JS number for display or charting.
 * Not safe for further arithmetic on money — format immediately with
 * formatMoney/formatNumber, or compare the raw strings if exactness matters.
 */
export function parseDecimal(value: string): number {
  // Number("") is 0 and Number(" ") is 0 in JS — neither is a valid decimal
  // string, so both must be rejected explicitly rather than silently
  // returning a plausible-looking 0.
  if (value.trim() === "") {
    throw new Error("Invalid decimal string: (empty)")
  }
  const n = Number(value)
  if (Number.isNaN(n)) {
    throw new Error(`Invalid decimal string: ${value}`)
  }
  return n
}

/**
 * Formats an already-numeric value as currency (e.g. a chart point parsed
 * once for plotting) — formatMoney is the entry point for a raw backend
 * decimal string; this is for a value that's already been through it.
 * Defaults to PKR, the org default per CLAUDE.md §1.3; pass the org's
 * actual currency once org settings expose one.
 */
export function formatMoneyValue(value: number, currency = "PKR", locale = "en-PK"): string {
  return new Intl.NumberFormat(locale, { style: "currency", currency }).format(value)
}

/**
 * Formats a backend decimal string as currency. See formatMoneyValue.
 */
export function formatMoney(value: string, currency = "PKR", locale = "en-PK"): string {
  return formatMoneyValue(parseDecimal(value), currency, locale)
}

/** Formats an already-numeric value with a bounded number of decimal places. */
export function formatNumberValue(value: number, maximumFractionDigits = 2, locale = "en-PK"): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits }).format(value)
}

/**
 * Formats a backend decimal string as a plain localized number (liters,
 * cost/km, reliability score, …) with a bounded number of decimal places.
 */
export function formatNumber(value: string, maximumFractionDigits = 2, locale = "en-PK"): string {
  return formatNumberValue(parseDecimal(value), maximumFractionDigits, locale)
}

/** Formats a plain integer/number (odometer, counts, …) with locale grouping. */
export function formatInt(value: number, locale = "en-PK"): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(value)
}
