"use client"

import { useState } from "react"
import { ChartLine } from "lucide-react"
import { useFuelLogs } from "@/lib/api/fuel"
import { useIncidents } from "@/lib/api/incidents"
import { useTrips } from "@/lib/api/trips"
import { formatNumber, formatRate } from "@/lib/api/decimal"
import { formatDate, formatDurationBetween } from "@/lib/format-date"
import { INCIDENT_TYPE_LABELS } from "@/lib/enum-labels"
import type { UserRole } from "@/lib/schemas/enums"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { AreaTrendChart } from "@/components/charts/area-trend-chart"
import { Callout } from "@/components/primitives/callout"
import { DataTable, type DataTableColumn } from "@/components/primitives/data-table"
import { SectionPanel } from "@/components/primitives/section-panel"
import { EmptyState } from "@/components/states/empty-state"
import { SkeletonChart } from "@/components/states/page-skeleton"
import { QueryRegion } from "@/components/states/query-boundary"
import type { TripLog } from "@/lib/schemas/trip"

const RANGE_OPTIONS = ["7", "30", "90"] as const

function daysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

function dailyDistance(trips: TripLog[], days: number): { date: string; km: number }[] {
  const byDate = new Map<string, number>()
  for (let i = days - 1; i >= 0; i--) {
    byDate.set(daysAgo(i), 0)
  }
  for (const trip of trips) {
    const date = trip.start_time.slice(0, 10)
    if (byDate.has(date)) byDate.set(date, (byDate.get(date) ?? 0) + trip.distance_km)
  }
  return Array.from(byDate.entries()).map(([date, km]) => ({ date, km }))
}

export function TripPanel({ vehicleId, role }: { vehicleId: string; role: UserRole | null }) {
  const [range, setRange] = useState<(typeof RANGE_OPTIONS)[number]>("30")
  const days = Number(range)
  const dateFrom = daysAgo(days - 1)

  const tripsQuery = useTrips({ vehicle_id: vehicleId, date_from: dateFrom })
  const fuelQuery = useFuelLogs({ vehicle_id: vehicleId, date_from: dateFrom })
  const incidentsQuery = useIncidents({ status: "open" })
  const investigatingQuery = useIncidents({ status: "investigating" })

  const title = role === "driver" ? "Your trips on this vehicle" : "Trip performance"

  return (
    <SectionPanel
      icon={ChartLine}
      title={title}
      action={
        <ToggleGroup type="single" value={range} onValueChange={(v) => v && setRange(v as (typeof RANGE_OPTIONS)[number])}>
          {RANGE_OPTIONS.map((r) => (
            <ToggleGroupItem key={r} value={r} aria-label={`Last ${r} days`}>
              {r}d
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      }
    >
      <QueryRegion
        query={tripsQuery}
        skeleton={<SkeletonChart />}
        empty={<EmptyState icon={ChartLine} title="No trips yet" description="Daily distance will chart here once trips are logged." />}
        isEmpty={(trips) => trips.length === 0}
        areaLabel="trip performance"
      >
        {(trips) => {
          const points = dailyDistance(trips, days)
          const anomalousFuel = (fuelQuery.data ?? []).filter((f) => f.is_anomalous).sort((a, b) => b.date.localeCompare(a.date))[0]
          const openIncidents = [...(incidentsQuery.data ?? []), ...(investigatingQuery.data ?? [])].filter((i) => i.vehicle_id === vehicleId)
          const latestIncident = [...openIncidents].sort((a, b) => b.date.localeCompare(a.date))[0]

          const recent = [...trips].sort((a, b) => b.start_time.localeCompare(a.start_time)).slice(0, 5)
          const columns: DataTableColumn<TripLog>[] = [
            { key: "date", header: "Date", cell: (t) => formatDate(t.start_time.slice(0, 10)) },
            { key: "distance", header: "Distance (km)", align: "right", cell: (t) => t.distance_km },
            { key: "duration", header: "Duration", cell: (t) => formatDurationBetween(t.start_time, t.end_time) },
            { key: "fuel", header: "Fuel used (L)", align: "right", cell: (t) => (t.fuel_consumed ? formatNumber(t.fuel_consumed) : "—") },
          ]

          return (
            <div className="space-y-4">
              <AreaTrendChart
                data={points}
                xKey="date"
                xFormatter={formatDate}
                series={[{ key: "km", label: "Distance", color: "var(--chart-1)", valueFormatter: (v) => `${v} km` }]}
              />

              {anomalousFuel ? (
                <Callout
                  title={`Unusual fuel cost on ${formatDate(anomalousFuel.date)}`}
                  detail={`Cost per km was ${formatRate(anomalousFuel.cost_per_km ?? "0")}, more than 20% off this vehicle's 3-month average.`}
                  href="/fuel"
                />
              ) : latestIncident ? (
                <Callout
                  title={`${openIncidents.length} open incident${openIncidents.length === 1 ? "" : "s"}`}
                  detail={`Latest: ${INCIDENT_TYPE_LABELS[latestIncident.incident_type]}, ${latestIncident.severity} on ${formatDate(latestIncident.date)}`}
                  href="/accountability"
                />
              ) : null}

              <DataTable columns={columns} rows={recent} getRowId={(t) => t.id} />
            </div>
          )
        }}
      </QueryRegion>
    </SectionPanel>
  )
}
