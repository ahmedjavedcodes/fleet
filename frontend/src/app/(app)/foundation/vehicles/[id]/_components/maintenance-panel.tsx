"use client"

import { CalendarCheck, Wrench } from "lucide-react"
import Link from "next/link"
import { useVehicleCompliance } from "@/lib/api/vehicles"
import { useMaintenanceLogs } from "@/lib/api/maintenance"
import { formatInt, formatMoney } from "@/lib/api/decimal"
import { formatDate } from "@/lib/format-date"
import { SERVICE_TYPE_LABELS } from "@/lib/enum-labels"
import { can } from "@/lib/rbac"
import type { ComplianceStatusItem } from "@/lib/schemas/compliance"
import type { UserRole } from "@/lib/schemas/enums"
import { Badge } from "@/components/ui/badge"
import { DueRow } from "@/components/fleet/due-row"
import { TimelineList } from "@/components/fleet/timeline-list"
import { InnerCard } from "@/components/primitives/inner-card"
import { SectionPanel } from "@/components/primitives/section-panel"
import { EmptyState } from "@/components/states/empty-state"
import { SkeletonPanel } from "@/components/states/page-skeleton"
import { QueryRegion } from "@/components/states/query-boundary"

function scheduleDueText(item: ComplianceStatusItem): string {
  if (item.status === "never_performed") return "Never performed"
  if (item.status === "overdue") return "Overdue"
  if (item.km_remaining !== null) return `Due in ${formatInt(item.km_remaining)} km`
  if (item.days_remaining !== null) return `Due in ${item.days_remaining} days`
  return "Due soon"
}

export function MaintenancePanel({ vehicleId, role }: { vehicleId: string; role: UserRole | null }) {
  const complianceQuery = useVehicleCompliance(vehicleId)
  const canSeeHistory = Boolean(role && can(role, "maintenance:read"))
  const canLogService = Boolean(role && can(role, "maintenance:write"))
  const logsQuery = useMaintenanceLogs({ vehicle_id: vehicleId }, { enabled: canSeeHistory })

  return (
    <SectionPanel icon={Wrench} title="Maintenance Overview">
      <div className="space-y-4">
        <InnerCard className="p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-foreground">Scheduled Service</h3>
            {canLogService ? (
              <Link href={`/maintenance?vehicle_id=${vehicleId}&new=1`} className="text-caption font-medium text-primary-strong hover:underline">
                + Log service
              </Link>
            ) : null}
          </div>
          <QueryRegion
            query={complianceQuery}
            skeleton={<SkeletonPanel />}
            empty={<EmptyState icon={CalendarCheck} title="No compliance rules apply" description="No compliance rules apply to this vehicle." />}
            isEmpty={(res) => res.items.length === 0}
            areaLabel="scheduled service"
          >
            {(res) => {
              const relevant = res.items.filter((i) => i.status === "overdue" || i.status === "due_soon" || i.status === "never_performed")
              if (relevant.length === 0) {
                return <EmptyState icon={CalendarCheck} title="Everything is up to date" description="No service is due or overdue." />
              }
              const sorted = [...relevant].sort((a, b) => (a.status === "overdue" ? 0 : 1) - (b.status === "overdue" ? 0 : 1))
              return (
                <div className="space-y-2">
                  {sorted.map((item) => (
                    <DueRow
                      key={item.rule.id}
                      icon={Wrench}
                      title={SERVICE_TYPE_LABELS[item.rule.service_type]}
                      dueText={scheduleDueText(item)}
                      status={item.status === "due_soon" ? "upcoming" : "overdue"}
                    />
                  ))}
                </div>
              )
            }}
          </QueryRegion>
        </InnerCard>

        {canSeeHistory ? (
          <InnerCard className="p-4">
            <h3 className="mb-3 text-sm font-semibold text-foreground">Service History</h3>
            <QueryRegion
              query={logsQuery}
              skeleton={<SkeletonPanel />}
              empty={<EmptyState icon={Wrench} title="No service history" description="Service records will appear here once logged." />}
              isEmpty={(logs) => logs.length === 0}
              areaLabel="service history"
            >
              {(logs) => {
                const recent = [...logs].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 5)
                return (
                  <TimelineList items={recent} getKey={(l) => l.id}>
                    {(log) => (
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-medium text-foreground">
                            {formatDate(log.date)} · {SERVICE_TYPE_LABELS[log.service_type]}
                          </p>
                          <p className="text-caption text-muted-foreground">
                            {log.mechanic_name ?? "—"}
                            {log.mechanic_report ? (
                              <Badge variant="outline" className="ml-2">
                                Report
                              </Badge>
                            ) : null}
                          </p>
                        </div>
                        <span className="shrink-0 text-caption font-medium text-foreground">{log.cost ? formatMoney(log.cost) : "—"}</span>
                      </div>
                    )}
                  </TimelineList>
                )
              }}
            </QueryRegion>
          </InnerCard>
        ) : null}
      </div>
    </SectionPanel>
  )
}
