"use client"

import { useDrivers } from "@/lib/api/drivers"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

const NONE = "__none__"

// Optional driver picker: "None" clears the value back to undefined so the
// field is simply omitted from the request.
export function DriverSelect({
  id,
  value,
  onChange,
  placeholder = "None",
}: {
  id: string
  value: string | undefined
  onChange: (driverId: string | undefined) => void
  placeholder?: string
}) {
  const driversQuery = useDrivers()
  return (
    <Select value={value ?? NONE} onValueChange={(v) => onChange(v === NONE ? undefined : v)}>
      <SelectTrigger id={id} className="w-full">
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NONE}>{placeholder}</SelectItem>
        {(driversQuery.data ?? []).map((d) => (
          <SelectItem key={d.id} value={d.id}>
            {d.full_name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
