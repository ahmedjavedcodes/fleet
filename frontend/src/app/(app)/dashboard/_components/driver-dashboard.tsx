"use client"

import { AlertTriangle, Fuel, Route, ShieldAlert, Truck, UserX } from "lucide-react"
import Link from "next/link"
import { useDriverAssignments } from "@/lib/api/drivers"
import { useFuelLogs } from "@/lib/api/fuel"
import { useIncidents } from "@/lib/api/incidents"
import { useTrips } from "@/lib/api/trips"
import { useVehicle } from "@/lib/api/vehicles"
import { useDriverTimeline } from "@/lib/api/drivers"
import { formatDate, formatDateTime, formatDurationBetween } from "@/lib/format-date"
import { formatInt, formatMoney, formatNumber } from "@/lib/api/decimal"
import { INCIDENT_SEVERITY_LABELS, INCIDENT_SEVERITY_TONE, INCIDENT_TYPE_LABELS, VEHICLE_CONDITION_LABELS } from "@/lib/enum-labels"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import type { VehicleAssignment } from "@/lib/schemas/assignment"
import type { FuelLog } from "@/lib/schemas/fuel"
import type { TripLog } from "@/lib/schemas/trip"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { DataTable, type DataTableColumn } from "@/components/primitives/data-table"
import { VehicleLink } from "@/components/fleet/vehicle-link"
import { IconTile } from "@/components/primitives/icon-tile"
import { SectionPanel } from "@/components/primitives/section-panel"
import { StatusPill } from "@/components/primitives/status-pill"
import { TimelineList } from "@/components/fleet/timeline-list"
import { PageHeader } from "@/components/layout/page-header"
import { EmptyState } from "@/components/states/empty-state"
import { Skeleton } from "@/components/ui/skeleton"
import { SkeletonPanel, SkeletonTable } from "@/components/states/page-skeleton"
import { QueryRegion } from "@/components/states/query-boundary"
import { Greeting } from "./greeting"

const FUEL_LIMIT = 5
const RECENT_COUNT = 5

export function DriverDashboard() {
  const { driverProfile, isPending } = useCurrentUser()

  const pageActions = (
    <div className="flex gap-2">
      <Button asChild variant="outline">
        <Link href="/fuel?new=1">Log fuel</Link>
      </Button>
      <Button asChild variant="outline">
        <Link href="/fuel?tab=trips&new=1">Log trip</Link>
      </Button>
    </div>
  )

  if (isPending) {
    return (
      <div className="space-y-6">
        <PageHeader crumbs={[{ label: "Overview" }]} />
        <Skeleton className="h-8 w-64" />
        <SkeletonPanel />
      </div>
    )
  }

  // The seeded test driver has no linked profile — an honest state rather
  // than calling endpoints that would 422/return empty (plans/04 §4).
  if (!driverProfile) {
    return (
      <div className="space-y-6">
        <PageHeader crumbs={[{ label: "Overview" }]} />
        <Greeting />
        <EmptyState
          icon={UserX}
          title="No driver profile linked"
          description="Your account isn't linked to a driver profile yet. Ask your fleet manager to link it."
        />
      </div>
    )
  }

  return <DriverDashboardContent driverId={driverProfile.id} pageActions={pageActions} />
}

function DriverDashboardContent({ driverId, pageActions }: { driverId: string; pageActions: React.ReactNode }) {
  const assignmentsQuery = useDriverAssignments(driverId)
  const fuelQuery = useFuelLogs({ limit: FUEL_LIMIT })
  const tripsQuery = useTrips()
  const incidentsQuery = useIncidents()
  const timelineQuery = useDriverTimeline(driverId)

  const fuelColumns: DataTableColumn<FuelLog>[] = [
    { key: "date", header: "Date", cell: (row) => formatDate(row.date) },
    { key: "liters", header: "Liters", align: "right", cell: (row) => formatNumber(row.liters_filled, 1) },
    { key: "total", header: "Total (PKR)", align: "right", cell: (row) => formatMoney(row.total_cost) },
    {
      key: "costPerKm",
      header: "Cost/km",
      align: "right",
      cell: (row) => (
        <span className="inline-flex items-center gap-1.5">
          {row.cost_per_km !== null ? formatNumber(row.cost_per_km) : "—"}
          {row.is_anomalous ? <Badge variant="warning">Anomaly</Badge> : null}
        </span>
      ),
    },
  ]

  const tripColumns: DataTableColumn<TripLog>[] = [
    { key: "date", header: "Date", cell: (row) => formatDate(row.start_time.slice(0, 10)) },
    { key: "vehicle_name", header: "Vehicle Name", cell: (row) => row.vehicle_name ?? "—" },
    { key: "vehicle_plate", header: "Vehicle Plate", cell: (row) => <VehicleLink vehicleId={row.vehicle_id} plate={row.vehicle_plate} /> },
    { key: "start_odometer", header: "Start Odometer", align: "right", cell: (row) => formatInt(row.start_odometer) },
    { key: "end_odometer", header: "End Odometer", align: "right", cell: (row) => formatInt(row.end_odometer) },
    { key: "distance", header: "Distance (km)", align: "right", cell: (row) => formatInt(row.distance_km) },
    { key: "duration", header: "Duration", align: "right", cell: (row) => formatDurationBetween(row.start_time, row.end_time) },
  ]

  return (
    <div className="space-y-6">
      <PageHeader crumbs={[{ label: "Overview" }]} actions={pageActions} />
      <Greeting />

      <SectionPanel icon={Truck} title="Current vehicle">
        <QueryRegion query={assignmentsQuery} skeleton={<SkeletonPanel />} areaLabel="your current vehicle">
          {(history) =>
            history.current_assignment ? (
              <CurrentVehicleCard assignment={history.current_assignment} />
            ) : (
              <EmptyState icon={Truck} title="No vehicle assigned" description="You don't currently have a vehicle assigned." />
            )
          }
        </QueryRegion>
      </SectionPanel>

      <div className="grid gap-4 lg:grid-cols-2">
        <SectionPanel icon={Fuel} title="Your fuel logs">
          <QueryRegion
            query={fuelQuery}
            skeleton={<SkeletonTable rows={FUEL_LIMIT} columns={4} />}
            empty={<EmptyState icon={Fuel} title="No fuel logged yet" description="Log your first fuel entry." action={
              <Button asChild variant="outline"><Link href="/fuel?new=1">Log fuel</Link></Button>
            } />}
            isEmpty={(logs) => logs.length === 0}
            areaLabel="your fuel logs"
          >
            {(logs) => <DataTable columns={fuelColumns} rows={logs} getRowId={(row) => row.id} />}
          </QueryRegion>
        </SectionPanel>

        <SectionPanel icon={Route} title="Your trips">
          <QueryRegion
            query={tripsQuery}
            skeleton={<SkeletonTable rows={RECENT_COUNT} columns={7} />}
            empty={<EmptyState icon={Route} title="No trips logged yet" description="Log your first trip." action={
              <Button asChild variant="outline"><Link href="/fuel?tab=trips&new=1">Log trip</Link></Button>
            } />}
            isEmpty={(trips) => trips.length === 0}
            areaLabel="your trips"
          >
            {(trips) => {
              const recent = [...trips].sort((a, b) => b.start_time.localeCompare(a.start_time)).slice(0, RECENT_COUNT)
              return <DataTable columns={tripColumns} rows={recent} getRowId={(row) => row.id} />
            }}
          </QueryRegion>
        </SectionPanel>
      </div>

      <SectionPanel icon={ShieldAlert} title="Your incidents">
        <QueryRegion
          query={incidentsQuery}
          skeleton={<SkeletonPanel />}
          empty={<EmptyState icon={ShieldAlert} title="No incidents reported" description="Incidents you report will appear here." />}
          isEmpty={(incidents) => incidents.length === 0}
          areaLabel="your incidents"
        >
          {(incidents) => (
            <div className="space-y-2">
              {incidents.map((incident) => (
                <div key={incident.id} className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-foreground">
                      {formatDate(incident.date)} · {INCIDENT_TYPE_LABELS[incident.incident_type]}
                    </p>
                    <p className="truncate text-caption text-muted-foreground">{incident.description}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <StatusPill tone={INCIDENT_SEVERITY_TONE[incident.severity]}>
                      {INCIDENT_SEVERITY_LABELS[incident.severity]}
                    </StatusPill>
                    <Badge variant="neutral">{incident.resolution_status}</Badge>
                  </div>
                </div>
              ))}
            </div>
          )}
        </QueryRegion>
      </SectionPanel>

      <SectionPanel icon={AlertTriangle} title="Your timeline">
        <QueryRegion
          query={timelineQuery}
          skeleton={<SkeletonPanel />}
          empty={<EmptyState icon={AlertTriangle} title="Nothing yet" description="Your trips, shift reports and incidents will show up here." />}
          isEmpty={(entries) => entries.length === 0}
          areaLabel="your timeline"
        >
          {(entries) => (
            <TimelineList items={entries} getKey={(entry) => entry.id}>
              {(entry) => (
                <div>
                  <p className="text-caption text-muted-foreground">{formatDateTime(entry.date)}</p>
                  {entry.record_type === "trip" && (
                    <p className="text-sm text-foreground">
                      Trip · {formatInt(entry.summary.distance_km)} km ·{" "}
                      {formatDurationBetween(entry.summary.start_time, entry.summary.end_time)}
                    </p>
                  )}
                  {entry.record_type === "report" && (
                    <p className="text-sm text-foreground">
                      Shift report · vehicle condition {VEHICLE_CONDITION_LABELS[entry.summary.vehicle_condition]}
                    </p>
                  )}
                  {entry.record_type === "incident" && (
                    <p className="text-sm text-foreground">
                      Incident · {INCIDENT_SEVERITY_LABELS[entry.summary.severity]} {INCIDENT_TYPE_LABELS[entry.summary.incident_type]}
                    </p>
                  )}
                </div>
              )}
            </TimelineList>
          )}
        </QueryRegion>
      </SectionPanel>
    </div>
  )
}

function CurrentVehicleCard({ assignment }: { assignment: VehicleAssignment }) {
  const vehicleQuery = useVehicle(assignment.vehicle_id)
  return (
    <QueryRegion query={vehicleQuery} skeleton={<Skeleton className="h-20 w-full rounded-xl" />} areaLabel="the vehicle">
      {(vehicle) => (
        <div className="flex items-center gap-4 rounded-xl border border-border bg-card p-4">
          <IconTile icon={Truck} tone="brand" size="lg" />
          <div>
            <p className="text-h2 text-foreground">{vehicle.plate_number}</p>
            <p className="text-sm text-muted-foreground">
              {vehicle.make} {vehicle.model}
            </p>
            <p className="text-caption text-muted-foreground">
              Since {formatDate(assignment.assigned_at.slice(0, 10))} · {formatInt(assignment.start_odometer)} km start
            </p>
          </div>
        </div>
      )}
    </QueryRegion>
  )
}
