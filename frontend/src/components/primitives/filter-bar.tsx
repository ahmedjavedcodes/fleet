"use client"

import { X } from "lucide-react"
import { ALL } from "@/lib/table-filters"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

export interface FilterSelect {
  /** Accessible name, e.g. "Filter by severity". */
  label: string
  value: string
  onChange: (value: string) => void
  /** Text for the "no filter" entry, e.g. "All severities". */
  allLabel: string
  options: { value: string; label: string }[]
}

export interface DateRangeFilter {
  from: string
  to: string
  onChange: (range: { from: string; to: string }) => void
}

// The search box + dropdowns (+ optional date range) row above a data table,
// matching the Vehicles page. Fully controlled: the page owns the filter state
// and does the filtering, so this stays presentational.
export function FilterBar({
  search,
  onSearchChange,
  searchPlaceholder,
  searchLabel,
  selects = [],
  dateRange,
}: {
  search: string
  onSearchChange: (value: string) => void
  searchPlaceholder: string
  searchLabel: string
  selects?: FilterSelect[]
  dateRange?: DateRangeFilter
}) {
  const dirty = search !== "" || selects.some((s) => s.value !== ALL) || Boolean(dateRange && (dateRange.from || dateRange.to))

  function clear() {
    onSearchChange("")
    selects.forEach((s) => s.onChange(ALL))
    dateRange?.onChange({ from: "", to: "" })
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <Input
        aria-label={searchLabel}
        placeholder={searchPlaceholder}
        value={search}
        onChange={(e) => onSearchChange(e.target.value)}
        className="max-w-xs"
      />
      {selects.map((s) => (
        <Select key={s.label} value={s.value} onValueChange={s.onChange}>
          <SelectTrigger aria-label={s.label} className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{s.allLabel}</SelectItem>
            {s.options.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ))}
      {dateRange ? (
        <div className="flex items-center gap-2">
          <Input
            type="date"
            aria-label="From date"
            value={dateRange.from}
            max={dateRange.to || undefined}
            onChange={(e) => dateRange.onChange({ from: e.target.value, to: dateRange.to })}
            className="w-40"
          />
          <span className="text-caption text-muted-foreground" aria-hidden>
            to
          </span>
          <Input
            type="date"
            aria-label="To date"
            value={dateRange.to}
            min={dateRange.from || undefined}
            onChange={(e) => dateRange.onChange({ from: dateRange.from, to: e.target.value })}
            className="w-40"
          />
        </div>
      ) : null}
      {dirty ? (
        <Button variant="ghost" size="sm" onClick={clear}>
          <X className="size-4" />
          Clear
        </Button>
      ) : null}
    </div>
  )
}
