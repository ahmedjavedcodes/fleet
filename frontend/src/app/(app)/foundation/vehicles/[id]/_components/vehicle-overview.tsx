"use client"

import { Fuel, Gauge, Hash, ShieldCheck, Truck, Users } from "lucide-react"
import Link from "next/link"
import { useVehicleCompliance } from "@/lib/api/vehicles"
import { useFuelSummary } from "@/lib/api/fuel"
import { useTrips } from "@/lib/api/trips"
import { formatInt } from "@/lib/api/decimal"
import { can } from "@/lib/rbac"
import type { Driver } from "@/lib/schemas/driver"
import type { UserRole } from "@/lib/schemas/enums"
import type { Vehicle } from "@/lib/schemas/vehicle"
import { InitialsAvatar } from "@/components/primitives/initials-avatar"
import { InnerCard } from "@/components/primitives/inner-card"
import { KpiTile } from "@/components/primitives/kpi-tile"

function MetaItem({ icon: Icon, children, mono }: { icon: React.ComponentType<{ className?: string }>; children: React.ReactNode; mono?: boolean }) {
  return (
    <span className="flex items-center gap-1.5 text-caption text-muted-foreground">
      <Icon className="size-3.5" aria-hidden />
      <span className={mono ? "font-mono" : undefined}>{children}</span>
    </span>
  )
}

function todayMonth(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`
}

function daysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

// Hero card + 2x2 KPI tiles. Assignment/driver data is fetched once at the
// page level (the topbar's "Contact Driver" action needs the same data) and
// passed in as props; this component owns only the KPI tiles' own queries
// (compliance, fuel summary, trips), since the topbar doesn't need those.
export function VehicleOverview({
  vehicle,
  role,
  canSeeAssignment,
  canWriteAssignment,
  currentAssignment,
  driver,
  onAssignClick,
}: {
  vehicle: Vehicle
  role: UserRole | null
  canSeeAssignment: boolean
  canWriteAssignment: boolean
  currentAssignment: { driver_id: string } | null
  driver: Driver | null | undefined
  onAssignClick: () => void
}) {
  const canSeeFuelSummary = Boolean(role && can(role, "fuel:summary"))
  const canSeeTrips = Boolean(role && can(role, "trip:read"))

  const complianceQuery = useVehicleCompliance(vehicle.id)
  const overdueCount = complianceQuery.data?.items.filter((i) => i.status === "overdue").length ?? null
  const dueSoonCount = complianceQuery.data?.items.filter((i) => i.status === "due_soon").length ?? null

  const fuelSummaryQuery = useFuelSummary(todayMonth(), { enabled: canSeeFuelSummary })
  const vehicleFuel = fuelSummaryQuery.data?.by_vehicle.find((v) => v.vehicle_id === vehicle.id)

  const tripsQuery = useTrips({ vehicle_id: vehicle.id, date_from: daysAgo(30) }, { enabled: canSeeTrips })

  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <InnerCard className="p-6 xl:col-span-2">
        <div className="flex flex-col gap-5 sm:flex-row">
          <div aria-hidden className="flex size-24 shrink-0 items-center justify-center self-start rounded-xl bg-panel">
            <Truck className="size-10 text-muted-foreground" />
          </div>
          <div className="min-w-0 flex-1 space-y-3">
            <div>
              <h1 className="text-h1 font-semibold text-foreground">{vehicle.plate_number}</h1>
              <p className="text-sm text-muted-foreground">
                {vehicle.make} {vehicle.model} · {vehicle.year}
              </p>
            </div>

            {canSeeAssignment ? (
              currentAssignment && driver ? (
                <div className="flex flex-wrap items-center gap-3">
                  <div className="flex items-center gap-2">
                    <InitialsAvatar fullName={driver.full_name} size="sm" />
                    <div>
                      <p className="text-caption text-muted-foreground">Driver assigned</p>
                      <Link href={`/foundation/drivers/${driver.id}`} className="text-sm font-medium text-foreground hover:underline">
                        {driver.full_name}
                      </Link>
                    </div>
                  </div>
                  <a href={`tel:${driver.phone}`} className="rounded-full border border-primary px-3 py-1 text-caption font-medium text-primary-strong">
                    {driver.phone}
                  </a>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <p className="text-sm text-muted-foreground">No driver assigned</p>
                  {canWriteAssignment ? (
                    <button onClick={onAssignClick} className="text-sm font-medium text-primary-strong hover:underline">
                      Assign
                    </button>
                  ) : null}
                </div>
              )
            ) : null}

            <div className="flex flex-wrap gap-4">
              <MetaItem icon={Gauge}>{formatInt(vehicle.current_odometer)} km</MetaItem>
              <MetaItem icon={Fuel}>{vehicle.fuel_type[0]!.toUpperCase() + vehicle.fuel_type.slice(1)}</MetaItem>
              <MetaItem icon={Hash} mono>
                {vehicle.vin}
              </MetaItem>
            </div>
            {vehicle.service_interval_km || vehicle.service_interval_months ? (
              <p className="text-caption text-muted-foreground">
                Service every{vehicle.service_interval_km ? ` ${formatInt(vehicle.service_interval_km)} km` : ""}
                {vehicle.service_interval_km && vehicle.service_interval_months ? " /" : ""}
                {vehicle.service_interval_months ? ` ${vehicle.service_interval_months} months` : ""}
              </p>
            ) : null}
          </div>
        </div>
      </InnerCard>

      <div className="grid grid-cols-2 gap-3 self-start">
        {canSeeFuelSummary ? (
          <KpiTile
            icon={Gauge}
            tone="green"
            label="Cost per km"
            value={vehicleFuel?.avg_cost_per_km ?? "0"}
            format="money"
            hint={!vehicleFuel?.avg_cost_per_km ? "No fuel logs this month" : undefined}
          />
        ) : null}
        {canSeeTrips ? (
          <KpiTile
            icon={Users}
            tone="blue"
            label={role === "driver" ? "Your trips" : "Trips (30 days)"}
            value={String(tripsQuery.data?.length ?? 0)}
            format="count"
          />
        ) : null}
        <KpiTile
          icon={ShieldCheck}
          tone={overdueCount ? "amber" : "green"}
          label="Compliance"
          value={overdueCount ? String(overdueCount) : "0"}
          format="count"
          unit={overdueCount ? "overdue" : "All current"}
          hint={dueSoonCount ? `${dueSoonCount} due soon` : undefined}
        />
        {canSeeFuelSummary ? (
          <KpiTile icon={Fuel} tone="purple" label="Fuel cost (month)" value={vehicleFuel?.total_cost ?? "0"} format="money" />
        ) : null}
      </div>
    </div>
  )
}
