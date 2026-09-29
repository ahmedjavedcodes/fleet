"use client"

import { useState } from "react"
import { Flag, Link2, Phone, UserMinus, UserPlus } from "lucide-react"
import { useParams } from "next/navigation"
import { toast } from "sonner"
import { isApiError } from "@/lib/api/errors"
import { useVehicle, useVehicleAssignments } from "@/lib/api/vehicles"
import { useDriver } from "@/lib/api/drivers"
import { can } from "@/lib/rbac"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { StatusPill, type StatusPillTone } from "@/components/primitives/status-pill"
import { PageHeader } from "@/components/layout/page-header"
import { ErrorState } from "@/components/states/error-state"
import { PageSkeleton } from "@/components/states/page-skeleton"
import { AssignDriverDialog, ReleaseDriverFlow } from "./_components/assign-release-dialog"
import { HealthPanel } from "./_components/health-panel"
import { MaintenancePanel } from "./_components/maintenance-panel"
import { TripPanel } from "./_components/trip-panel"
import { VehicleOverview } from "./_components/vehicle-overview"

const STATUS_LABEL: Record<string, { label: string; tone: StatusPillTone }> = {
  active: { label: "Active", tone: "success" },
  maintenance: { label: "In maintenance", tone: "warning" },
  retired: { label: "Retired", tone: "neutral" },
}

export default function VehicleDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { role } = useCurrentUser()
  const [assignOpen, setAssignOpen] = useState(false)
  const [releaseOpen, setReleaseOpen] = useState(false)

  const vehicleQuery = useVehicle(id)

  const canSeeAssignment = Boolean(role && can(role, "vehicle:assignments:read"))
  const canWriteAssignment = Boolean(role && can(role, "vehicle:write"))
  const canSeeHealth = Boolean(role && can(role, "dashboard:read"))
  const canSeeTrips = Boolean(role && can(role, "trip:read"))
  const canReportIncident = Boolean(role && can(role, "incident:create"))

  const assignmentsQuery = useVehicleAssignments(id, undefined, { enabled: canSeeAssignment })
  const currentAssignment = assignmentsQuery.data?.find((a) => a.released_at === null) ?? null
  const driverQuery = useDriver(currentAssignment?.driver_id ?? "")

  async function copyLink() {
    await navigator.clipboard.writeText(window.location.href)
    toast.success("Link copied")
  }

  if (vehicleQuery.isPending) {
    return (
      <div className="space-y-6">
        <PageHeader crumbs={[{ label: "Fleet", href: "/foundation/vehicles" }, { label: "Vehicles", href: "/foundation/vehicles" }, { label: "…" }]} />
        <PageSkeleton />
      </div>
    )
  }

  if (vehicleQuery.error) {
    return (
      <div className="space-y-6">
        <PageHeader crumbs={[{ label: "Fleet", href: "/foundation/vehicles" }, { label: "Vehicles", href: "/foundation/vehicles" }, { label: "Not found" }]} />
        <ErrorState
          error={isApiError(vehicleQuery.error) ? vehicleQuery.error : { kind: "network" }}
          onRetry={() => void vehicleQuery.refetch()}
        />
      </div>
    )
  }

  const vehicle = vehicleQuery.data!
  const statusInfo = STATUS_LABEL[vehicle.status] ?? { label: vehicle.status, tone: "neutral" as const }

  return (
    <div className="space-y-6">
      <PageHeader
        crumbs={[
          { label: "Fleet", href: "/foundation/vehicles" },
          { label: "Vehicles", href: "/foundation/vehicles" },
          { label: `${vehicle.plate_number} — ${vehicle.make} ${vehicle.model} ${vehicle.year}` },
        ]}
        status={<StatusPill tone={statusInfo.tone}>{statusInfo.label}</StatusPill>}
        actions={
          <div className="flex items-center gap-1">
            {canSeeAssignment && currentAssignment && driverQuery.data ? (
              <Button asChild variant="outline" size="sm">
                <a href={`tel:${driverQuery.data.phone}`}>
                  <Phone className="size-4" />
                  Contact driver
                </a>
              </Button>
            ) : null}
            {canWriteAssignment ? (
              currentAssignment ? (
                <Button variant="outline" size="sm" onClick={() => setReleaseOpen(true)}>
                  <UserMinus className="size-4" />
                  Release driver
                </Button>
              ) : (
                <Button variant="outline" size="sm" onClick={() => setAssignOpen(true)}>
                  <UserPlus className="size-4" />
                  Assign driver
                </Button>
              )
            ) : null}
            {canReportIncident ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button asChild variant="outline" size="icon-sm">
                    <a href={`/accountability?vehicle_id=${vehicle.id}&new=1`} aria-label="Report incident">
                      <Flag className="size-4" />
                    </a>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Report incident</TooltipContent>
              </Tooltip>
            ) : null}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="outline" size="icon-sm" onClick={() => void copyLink()} aria-label="Copy link">
                  <Link2 className="size-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Copy link</TooltipContent>
            </Tooltip>
          </div>
        }
      />

      <VehicleOverview
        vehicle={vehicle}
        role={role}
        canSeeAssignment={canSeeAssignment}
        canWriteAssignment={canWriteAssignment}
        currentAssignment={currentAssignment}
        driver={driverQuery.data}
        onAssignClick={() => setAssignOpen(true)}
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <MaintenancePanel vehicleId={vehicle.id} role={role} />
        {canSeeTrips ? <TripPanel vehicleId={vehicle.id} role={role} /> : null}
        {canSeeHealth ? <HealthPanel vehicleId={vehicle.id} /> : null}
      </div>

      {canWriteAssignment ? (
        <>
          <AssignDriverDialog open={assignOpen} onOpenChange={setAssignOpen} vehicleId={vehicle.id} currentOdometer={vehicle.current_odometer} />
          <ReleaseDriverFlow open={releaseOpen} onOpenChange={setReleaseOpen} vehicleId={vehicle.id} currentOdometer={vehicle.current_odometer} />
        </>
      ) : null}
    </div>
  )
}
