import { formatDateTime } from "@/lib/format-date"
import type { TimelineEntry } from "@/lib/schemas/timeline"
import { VehicleLink } from "@/components/fleet/vehicle-link"

function odometerLabel(entry: TimelineEntry): string | null {
  const fmt = (n: number) => n.toLocaleString("en-US")
  if (entry.record_type === "trip") {
    return `Odometer: ${fmt(entry.summary.start_odometer)} → ${fmt(entry.summary.end_odometer)}`
  }
  return entry.summary.odometer === null ? null : `Odometer: ${fmt(entry.summary.odometer)}`
}

export function DriverTimelineItem({ entry }: { entry: TimelineEntry }) {
  const odometer = odometerLabel(entry)
  return (
    <div className="text-sm">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
        <p className="font-medium text-foreground">
          {formatDateTime(entry.date)} · {entry.record_type[0]!.toUpperCase() + entry.record_type.slice(1)}
        </p>
        <VehicleLink vehicleId={entry.summary.vehicle_id} plate={entry.summary.vehicle_plate} name={entry.summary.vehicle_name} />
      </div>
      {odometer ? <p className="mt-0.5 text-caption text-muted-foreground">{odometer}</p> : null}
    </div>
  )
}
