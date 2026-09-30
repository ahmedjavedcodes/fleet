// Client-side table filtering shared by every list page's FilterBar.

export const ALL = "all"

/** True when every whitespace-separated term in `query` appears in at least one
 * field (case-insensitive). A blank query matches everything, and null/undefined
 * fields are ignored. */
export function matchesSearch(query: string, ...fields: (string | null | undefined)[]): boolean {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean)
  if (terms.length === 0) return true
  const haystack = fields.filter((f): f is string => Boolean(f)).map((f) => f.toLowerCase())
  return terms.every((term) => haystack.some((field) => field.includes(term)))
}

/** Inclusive range check on the calendar-date part (YYYY-MM-DD) of a date or
 * ISO timestamp. An empty bound is open-ended. */
export function inDateRange(value: string, from: string, to: string): boolean {
  const day = value.slice(0, 10)
  if (from && day < from) return false
  if (to && day > to) return false
  return true
}

/** Distinct non-empty values of a free-text field, sorted, as dropdown options. */
export function distinctOptions(values: (string | null | undefined)[]): { value: string; label: string }[] {
  return [...new Set(values.filter((v): v is string => Boolean(v)))].sort().map((v) => ({ value: v, label: v }))
}
