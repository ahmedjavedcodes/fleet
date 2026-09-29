// Small date-formatting helpers built on Intl.DateTimeFormat (CLAUDE.md
// §1.3) for the backend's plain date-ish string shapes.

/** "2026-06" -> "Jun 26" (a dashboard/fuel-trends month point). */
export function formatMonthLabel(month: string, locale = "en-PK"): string {
  const [year, monthNum] = month.split("-").map(Number)
  const date = new Date(Date.UTC(year, monthNum - 1, 1))
  return new Intl.DateTimeFormat(locale, { month: "short", year: "2-digit", timeZone: "UTC" }).format(date)
}

/** "2026-06-12" -> "12 Jun 2026". */
export function formatDate(dateString: string, locale = "en-PK"): string {
  const [year, month, day] = dateString.split("-").map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  return new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(
    date
  )
}

/** An ISO datetime string -> "12 Jun 2026, 14:05". */
export function formatDateTime(isoString: string, locale = "en-PK"): string {
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(isoString))
}

/** Duration between two ISO datetimes, formatted like "2h 15m". */
export function formatDurationBetween(startIso: string, endIso: string): string {
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime()
  const totalMinutes = Math.max(0, Math.round(ms / 60_000))
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  if (hours === 0) return `${minutes}m`
  if (minutes === 0) return `${hours}h`
  return `${hours}h ${minutes}m`
}
