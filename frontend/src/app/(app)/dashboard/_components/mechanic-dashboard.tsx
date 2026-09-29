"use client"

import { useMemo } from "react"
import { CheckCircle2, ClipboardList, PackageMinus, ShieldCheck, Wrench } from "lucide-react"
import Link from "next/link"
import { useLowStockParts } from "@/lib/api/inventory"
import { useMaintenanceLogs } from "@/lib/api/maintenance"
import { useFleetComplianceMatrix } from "@/lib/api/compliance"
import { useVehicles } from "@/lib/api/vehicles"
import { formatDate } from "@/lib/format-date"
import { formatMoney } from "@/lib/api/decimal"
import { can } from "@/lib/rbac"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import { SERVICE_TYPE_LABELS } from "@/lib/enum-labels"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { DataTable, type DataTableColumn } from "@/components/primitives/data-table"
import { SectionPanel } from "@/components/primitives/section-panel"
import { StatusPill } from "@/components/primitives/status-pill"
import { DueRow } from "@/components/fleet/due-row"
import { TimelineList } from "@/components/fleet/timeline-list"
import { PageHeader } from "@/components/layout/page-header"
import { EmptyState } from "@/components/states/empty-state"
import { SkeletonPanel, SkeletonTable } from "@/components/states/page-skeleton"
import { QueryRegion } from "@/components/states/query-boundary"
import type { LowStockResponse } from "@/lib/schemas/inventory"
import { Greeting } from "./greeting"

const RECENT_WORK_COUNT = 10

export function MechanicDashboard() {
  const { role } = useCurrentUser()
  const vehiclesQuery = useVehicles()
  const recentWorkQuery = useMaintenanceLogs()
  const lowStockQuery = useLowStockParts()
  const complianceQuery = useFleetComplianceMatrix()

  const plateByVehicleId = useMemo(() => {
    const map = new Map<string, string>()
    for (const vehicle of vehiclesQuery.data ?? []) map.set(vehicle.id, vehicle.plate_number)
    return map
  }, [vehiclesQuery.data])

  const lowStockColumns: DataTableColumn<LowStockResponse>[] = [
    { key: "name", header: "Part", cell: (row) => row.name },
    { key: "onHand", header: "On hand", align: "right", cell: (row) => row.qty_on_hand },
    { key: "reorder", header: "Reorder level", align: "right", cell: (row) => row.reorder_threshold },
    { key: "deficit", header: "Deficit", align: "right", cell: (row) => <span className="font-medium text-destructive">{row.deficit}</span> },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        crumbs={[{ label: "Overview" }]}
        actions={
          role && can(role, "maintenance:write") ? (
            <Button asChild variant="outline">
              <Link href="/maintenance?new=1">Log service</Link>
            </Button>
          ) : undefined
        }
      />
      <Greeting />

      <SectionPanel icon={Wrench} title="Recent work">
        <QueryRegion
          query={recentWorkQuery}
          skeleton={<SkeletonPanel />}
          empty={<EmptyState icon={Wrench} title="No service logged yet" description="Recent maintenance work will appear here." />}
          isEmpty={(logs) => logs.length === 0}
          areaLabel="recent maintenance work"
        >
          {(logs) => {
            const recent = [...logs].sort((a, b) => b.date.localeCompare(a.date)).slice(0, RECENT_WORK_COUNT)
            return (
              <TimelineList items={recent} getKey={(log) => log.id}>
                {(log) => (
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-foreground">
                        {SERVICE_TYPE_LABELS[log.service_type]} · {plateByVehicleId.get(log.vehicle_id) ?? "—"}
                      </p>
                      <p className="text-caption text-muted-foreground">{formatDate(log.date)}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      {log.mechanic_report ? (
                        <Badge variant="success">
                          <CheckCircle2 aria-hidden /> Report filed
                        </Badge>
                      ) : null}
                      {log.cost ? <span className="text-sm text-muted-foreground">{formatMoney(log.cost)}</span> : null}
                    </div>
                  </div>
                )}
              </TimelineList>
            )
          }}
        </QueryRegion>
      </SectionPanel>

      <div className="grid gap-4 lg:grid-cols-2">
        <SectionPanel icon={PackageMinus} title="Low stock">
          <QueryRegion
            query={lowStockQuery}
            skeleton={<SkeletonTable rows={4} columns={4} />}
            empty={<EmptyState icon={PackageMinus} title="Stock is healthy" description="No parts are below their reorder threshold." />}
            isEmpty={(parts) => parts.length === 0}
            areaLabel="low-stock parts"
          >
            {(parts) => <DataTable columns={lowStockColumns} rows={parts} getRowId={(row) => row.id} />}
          </QueryRegion>
        </SectionPanel>

        <SectionPanel icon={ShieldCheck} title="Compliance">
          <QueryRegion
            query={complianceQuery}
            skeleton={<SkeletonPanel />}
            empty={<EmptyState icon={ClipboardList} title="No compliance rules yet" description="Compliance status appears once rules are set up." />}
            isEmpty={(matrix) => matrix.every((entry) => entry.items.length === 0)}
            areaLabel="compliance status"
          >
            {(matrix) => {
              const worstFirst = matrix
                .flatMap((entry) =>
                  entry.items
                    .filter((item) => item.status === "overdue" || item.status === "due_soon")
                    .map((item) => ({ vehicleId: entry.vehicle_id, item }))
                )
                .sort((a, b) => (a.item.status === "overdue" ? 0 : 1) - (b.item.status === "overdue" ? 0 : 1))

              if (worstFirst.length === 0) {
                return <StatusPill tone="success">All vehicles current</StatusPill>
              }

              return (
                <div className="space-y-2">
                  {worstFirst.slice(0, 8).map(({ vehicleId, item }) => (
                    <DueRow
                      key={`${vehicleId}-${item.rule.service_type}`}
                      icon={Wrench}
                      title={plateByVehicleId.get(vehicleId) ?? "—"}
                      subtitle={SERVICE_TYPE_LABELS[item.rule.service_type]}
                      dueText={
                        item.days_remaining !== null
                          ? `${item.days_remaining} day(s)`
                          : item.km_remaining !== null
                            ? `${item.km_remaining} km`
                            : "—"
                      }
                      status={item.status === "overdue" ? "overdue" : "upcoming"}
                      href={`/foundation/vehicles/${vehicleId}`}
                    />
                  ))}
                </div>
              )
            }}
          </QueryRegion>
        </SectionPanel>
      </div>
    </div>
  )
}
