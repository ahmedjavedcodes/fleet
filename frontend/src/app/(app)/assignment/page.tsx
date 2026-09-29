"use client"

import { useState } from "react"
import { useQueries } from "@tanstack/react-query"
import { ArrowLeftRight, UserMinus, UserPlus } from "lucide-react"
import Link from "next/link"
import { getVehicleAssignments, useVehicles } from "@/lib/api/vehicles"
import { useDriver } from "@/lib/api/drivers"
import { vehicleKeys } from "@/lib/query/keys"
import { formatDateTime } from "@/lib/format-date"
import { can } from "@/lib/rbac"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import type { Vehicle } from "@/lib/schemas/vehicle"
import { AssignDriverDialog, ReleaseDriverFlow } from "@/components/fleet/assign-release-dialog"
import { Button } from "@/components/ui/button"
import { DataTable, type DataTableColumn } from "@/components/primitives/data-table"
import { PageHeader } from "@/components/layout/page-header"
import { EmptyState } from "@/components/states/empty-state"
import { PageSkeleton } from "@/components/states/page-skeleton"
import { QueryRegion } from "@/components/states/query-boundary"

function CurrentDriverCell({ driverId }: { driverId: string | null }) {
  const driverQuery = useDriver(driverId ?? "")
  if (!driverId) return <span className="text-muted-foreground">Unassigned</span>
  return (
    <Link href={`/foundation/drivers/${driverId}`} className="font-medium text-foreground hover:underline">
      {driverQuery.data?.full_name ?? "…"}
    </Link>
  )
}

// A/FM only — CLAUDE.md §2.1: no "list active assignments" endpoint, so this
// fans out GET /vehicles/{id}/assignments per vehicle. Flagged as a backend
// gap (plans/00 §6); acceptable for a fleet this size, but would need a real
// endpoint before this scales.
export default function AssignmentPage() {
  const { role } = useCurrentUser()
  const canWrite = Boolean(role && can(role, "vehicle:assign"))
  const vehiclesQuery = useVehicles()
  const vehicles = vehiclesQuery.data ?? []

  const [assigning, setAssigning] = useState<Vehicle | undefined>(undefined)
  const [releasing, setReleasing] = useState<Vehicle | undefined>(undefined)

  const assignmentQueries = useQueries({
    queries: vehicles.map((v) => ({
      queryKey: vehicleKeys.assignments(v.id),
      queryFn: () => getVehicleAssignments(v.id),
      enabled: vehicles.length > 0,
    })),
  })

  const columns: DataTableColumn<Vehicle>[] = [
    {
      key: "vehicle",
      header: "Vehicle",
      cell: (row) => (
        <Link href={`/foundation/vehicles/${row.id}`} className="font-semibold text-foreground hover:underline">
          {row.plate_number}
        </Link>
      ),
    },
    {
      key: "driver",
      header: "Current driver",
      cell: (row) => {
        const idx = vehicles.findIndex((v) => v.id === row.id)
        const current = assignmentQueries[idx]?.data?.find((a) => a.released_at === null) ?? null
        return <CurrentDriverCell driverId={current?.driver_id ?? null} />
      },
    },
    {
      key: "since",
      header: "Since",
      cell: (row) => {
        const idx = vehicles.findIndex((v) => v.id === row.id)
        const current = assignmentQueries[idx]?.data?.find((a) => a.released_at === null) ?? null
        return current ? formatDateTime(current.assigned_at) : "—"
      },
    },
  ]
  if (canWrite) {
    columns.push({
      key: "actions",
      header: "",
      align: "right",
      cell: (row) => {
        const idx = vehicles.findIndex((v) => v.id === row.id)
        const current = assignmentQueries[idx]?.data?.find((a) => a.released_at === null) ?? null
        return current ? (
          <Button variant="outline" size="sm" onClick={(e) => { e.stopPropagation(); setReleasing(row) }}>
            <UserMinus className="size-4" />
            Release
          </Button>
        ) : (
          <Button variant="outline" size="sm" onClick={(e) => { e.stopPropagation(); setAssigning(row) }}>
            <UserPlus className="size-4" />
            Assign
          </Button>
        )
      },
    })
  }

  return (
    <div className="space-y-6">
      <PageHeader crumbs={[{ label: "Operations" }, { label: "Assignment" }]} />

      <QueryRegion
        query={vehiclesQuery}
        skeleton={<PageSkeleton />}
        empty={<EmptyState icon={ArrowLeftRight} title="No vehicles yet" description="Custody assignments appear here once vehicles are added." />}
        isEmpty={(rows) => rows.length === 0}
        areaLabel="the custody board"
      >
        {(rows) => <DataTable columns={columns} rows={rows} getRowId={(r) => r.id} />}
      </QueryRegion>

      <p className="text-caption text-muted-foreground">
        The &quot;who had it on…&quot; date lookup isn&apos;t built yet — use a vehicle&apos;s own history on its detail page.
      </p>

      {assigning ? (
        <AssignDriverDialog open onOpenChange={(open) => !open && setAssigning(undefined)} vehicleId={assigning.id} currentOdometer={assigning.current_odometer} />
      ) : null}
      {releasing ? (
        <ReleaseDriverFlow open onOpenChange={(open) => !open && setReleasing(undefined)} vehicleId={releasing.id} currentOdometer={releasing.current_odometer} />
      ) : null}
    </div>
  )
}
