"use client"

import { useState } from "react"
import { Plus, Wrench } from "lucide-react"
import { useSearchParams } from "next/navigation"
import { useMaintenanceLogs } from "@/lib/api/maintenance"
import { formatMoney } from "@/lib/api/decimal"
import { formatDate } from "@/lib/format-date"
import { SERVICE_TYPE_LABELS } from "@/lib/enum-labels"
import { can } from "@/lib/rbac"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import type { MaintenanceLog } from "@/lib/schemas/maintenance"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { DataTable, type DataTableColumn } from "@/components/primitives/data-table"
import { PageHeader } from "@/components/layout/page-header"
import { AccessDenied } from "@/components/states/access-denied"
import { EmptyState } from "@/components/states/empty-state"
import { PageSkeleton } from "@/components/states/page-skeleton"
import { QueryRegion } from "@/components/states/query-boundary"
import { MaintenanceFormDialog } from "./_components/maintenance-form-dialog"

export default function MaintenancePage() {
  const { role } = useCurrentUser()
  const searchParams = useSearchParams()
  const vehicleId = searchParams.get("vehicle_id") ?? undefined

  const canRead = Boolean(role && can(role, "maintenance:read"))
  const canWrite = Boolean(role && can(role, "maintenance:write"))

  const [formOpen, setFormOpen] = useState(searchParams.get("new") === "1")

  const logsQuery = useMaintenanceLogs(vehicleId ? { vehicle_id: vehicleId } : {}, { enabled: canRead })

  const columns: DataTableColumn<MaintenanceLog>[] = [
    { key: "date", header: "Date", cell: (r) => formatDate(r.date) },
    { key: "service_type", header: "Service", cell: (r) => SERVICE_TYPE_LABELS[r.service_type] },
    { key: "cost", header: "Cost", align: "right", cell: (r) => (r.cost ? formatMoney(r.cost) : "—") },
    { key: "mechanic", header: "Mechanic", cell: (r) => r.mechanic_name ?? "—" },
    { key: "report", header: "", cell: (r) => (r.mechanic_report ? <Badge variant="outline">Report</Badge> : null) },
  ]

  if (!canRead) {
    return (
      <div className="space-y-6">
        <PageHeader crumbs={[{ label: "Operations" }, { label: "Maintenance" }]} />
        <AccessDenied area="maintenance" allowedRoles={["admin", "fleet_manager", "mechanic"]} />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        crumbs={[{ label: "Operations" }, { label: "Maintenance" }]}
        actions={
          canWrite ? (
            <Button onClick={() => setFormOpen(true)}>
              <Plus className="size-4" />
              Log service
            </Button>
          ) : undefined
        }
      />

      <QueryRegion
        query={logsQuery}
        skeleton={<PageSkeleton />}
        empty={<EmptyState icon={Wrench} title="No service logged yet" description="Service records will appear here once logged." />}
        isEmpty={(rows) => rows.length === 0}
        areaLabel="maintenance logs"
      >
        {(rows) => {
          const sorted = [...rows].sort((a, b) => b.date.localeCompare(a.date))
          return <DataTable columns={columns} rows={sorted} getRowId={(r) => r.id} />
        }}
      </QueryRegion>

      <p className="text-caption text-muted-foreground">
        Upcoming/overdue calendars, compliance rules, inventory and purchase orders aren&apos;t built yet — the service log above is
        complete.
      </p>

      <MaintenanceFormDialog open={formOpen} onOpenChange={setFormOpen} defaultVehicleId={vehicleId} />
    </div>
  )
}
