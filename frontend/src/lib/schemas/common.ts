import { z } from "zod"

// Pydantic v2 serializes Decimal fields to JSON as strings (e.g. "12.3400"),
// not numbers — never parse these with z.coerce.number() or do float math on
// them (CLAUDE.md §1.3, §7). Use lib/api/decimal.ts to convert for display.
export const decimalStringSchema = z.string().regex(/^-?\d+(\.\d+)?$/, "Expected a decimal string")

export const uuidSchema = z.string().uuid()

// Pydantic `date` fields serialize as "YYYY-MM-DD".
export const dateStringSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Expected YYYY-MM-DD")

// Pydantic `datetime` fields serialize as ISO 8601. Accept with or without an
// explicit offset/Z rather than over-constraining against a backend detail
// that isn't part of the contract.
export const dateTimeStringSchema = z.string().refine((v) => !Number.isNaN(Date.parse(v)), "Expected an ISO datetime")
