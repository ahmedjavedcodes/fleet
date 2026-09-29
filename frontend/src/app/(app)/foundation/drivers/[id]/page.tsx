"use client"

import { Car, Users } from "lucide-react"
import { useParams } from "next/navigation"
import { useDriver, useDriverAssignments, useDriverTimeline } from "@/lib/api/drivers"
import { isApiError } from "@/lib/api/errors"
import { formatDate, formatDateTime } from "@/lib/format-date"
import { can } from "@/lib/rbac"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import { InitialsAvatar } from "@/components/primitives/initials-avatar"
import { InnerCard } from "@/components/primitives/inner-card"
import { KpiTile } from "@/components/primitives/kpi-tile"
import { SectionPanel } from "@/components/primitives/section-panel"
import { StatusPill } from "@/components/primitives/status-pill"
import { DataTable, type DataTableColumn } from "@/components/primitives/data-table"
import { VehicleLink } from "@/components/fleet/vehicle-link"
import { TimelineList } from "@/components/fleet/timeline-list"
import { PageHeader } from "@/components/layout/page-header"
import { EmptyState } from "@/components/states/empty-state"
import { ErrorState } from "@/components/states/error-state"
import { PageSkeleton } from "@/components/states/page-skeleton"
import { QueryRegion } from "@/components/states/query-boundary"
import type { VehicleAssignment } from "@/lib/schemas/assignment"

export default function DriverDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { role } = useCurrentUser()
  const driverQuery = useDriver(id)
  const canSeeAssignments = Boolean(role && can(role, "driver:assignments"))
  const canSeeTimeline = Boolean(role && can(role, "driver:timeline"))
  const assignmentsQuery = useDriverAssignments(id)
  const timelineQuery = useDriverTimeline(id)

  if (driverQuery.isPending) {
    return (
      <div className="space-y-6">
        <PageHeader crumbs={[{ label: "Fleet", href: "/foundation/drivers" }, { label: "Drivers", href: "/foundation/drivers" }, { label: "…" }]} />
        <PageSkeleton />
      </div>
    )
  }

  if (driverQuery.error) {
    return (
      <div className="space-y-6">
        <PageHeader crumbs={[{ label: "Fleet", href: "/foundation/drivers" }, { label: "Drivers", href: "/foundation/drivers" }, { label: "Not found" }]} />
        <ErrorState error={isApiError(driverQuery.error) ? driverQuery.error : { kind: "network" }} onRetry={() => void driverQuery.refetch()} />
      </div>
    )
  }

  const driver = driverQuery.data!

  const historyColumns: DataTableColumn<VehicleAssignment>[] = [
    {
      key: "vehicle",
      header: "Vehicle",
      cell: (row) => <VehicleLink vehicleId={row.vehicle_id} plate={row.vehicle_plate} name={row.vehicle_name} />,
    },
    { key: "assigned", header: "Assigned", cell: (row) => formatDateTime(row.assigned_at) },
    { key: "released", header: "Released", cell: (row) => (row.released_at ? formatDateTime(row.released_at) : "Active") },
    { key: "duration", header: "Duration (h)", align: "right", cell: (row) => (row.duration_hours ? row.duration_hours.toFixed(1) : "—") },
  ]

  return (
    <div className="space-y-6">
      <PageHeader crumbs={[{ label: "Fleet", href: "/foundation/drivers" }, { label: "Drivers", href: "/foundation/drivers" }, { label: driver.full_name }]} />

      <InnerCard className="flex flex-col gap-4 p-6 sm:flex-row sm:items-center">
        <InitialsAvatar fullName={driver.full_name} size="lg" />
        <div className="flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-h1 font-semibold text-foreground">{driver.full_name}</h1>
            <StatusPill tone={driver.status === "active" ? "success" : "neutral"}>{driver.status[0]!.toUpperCase() + driver.status.slice(1)}</StatusPill>
          </div>
          <p className="text-sm text-muted-foreground">
            License {driver.license_number} · expires {formatDate(driver.license_expiry)}
          </p>
          <a href={`tel:${driver.phone}`} className="mt-1 inline-block rounded-full border border-primary px-3 py-1 text-caption font-medium text-primary-strong">
            {driver.phone}
          </a>
        </div>
      </InnerCard>

      {canSeeAssignments ? (
        <QueryRegion query={assignmentsQuery} skeleton={<PageSkeleton />} areaLabel="assignment history">
          {(res) => (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 sm:max-w-md">
                <KpiTile icon={Car} tone="blue" label="Vehicles driven" value={String(res.total_vehicles_driven)} format="count" />
                <KpiTile
                  icon={Car}
                  tone="green"
                  label="Current vehicle"
                  value={res.current_assignment ? "1" : "0"}
                  format="count"
                  hint={res.current_assignment ? undefined : "No vehicle assigned"}
                />
              </div>
              <SectionPanel icon={Car} title="Assignment history">
                {res.history.length === 0 ? (
                  <EmptyState icon={Car} title="No assignment history" description="Vehicle assignments will appear here." />
                ) : (
                  <DataTable columns={historyColumns} rows={res.history} getRowId={(row) => row.id} />
                )}
              </SectionPanel>
            </div>
          )}
        </QueryRegion>
      ) : null}

      {canSeeTimeline ? (
        <SectionPanel icon={Users} title="Timeline">
          <QueryRegion
            query={timelineQuery}
            skeleton={<PageSkeleton />}
            empty={<EmptyState icon={Users} title="No activity yet" description="Trips, reports and incidents will appear here." />}
            isEmpty={(items) => items.length === 0}
            areaLabel="the driver timeline"
          >
            {(items) => (
              <TimelineList items={items} getKey={(item) => item.id}>
                {(item) => (
                  <div className="text-sm">
                    <p className="font-medium text-foreground">
                      {formatDateTime(item.date)} · {item.record_type[0]!.toUpperCase() + item.record_type.slice(1)}
                    </p>
                  </div>
                )}
              </TimelineList>
            )}
          </QueryRegion>
        </SectionPanel>
      ) : null}
    </div>
  )
}
