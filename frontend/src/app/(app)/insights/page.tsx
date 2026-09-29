"use client"

import { useState } from "react"
import { ChartLine, ListChecks, Search, ShieldAlert } from "lucide-react"
import Link from "next/link"
import { useFleetHealth, useFuelTrends, useMaintenanceCalendar } from "@/lib/api/dashboard"
import { formatInt, formatMoneyValue, formatNumberValue, parseDecimal } from "@/lib/api/decimal"
import { formatDate, formatMonthLabel } from "@/lib/format-date"
import { healthScoreLabel } from "@/lib/health-score"
import { can } from "@/lib/rbac"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import type { MaintenanceCalendarItem, VehicleHealthScore } from "@/lib/schemas/dashboard"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { AreaTrendChart } from "@/components/charts/area-trend-chart"
import { HealthGauge } from "@/components/charts/health-gauge"
import { DueRow } from "@/components/fleet/due-row"
import { DataTable, type DataTableColumn } from "@/components/primitives/data-table"
import { SectionPanel } from "@/components/primitives/section-panel"
import { StatusPill } from "@/components/primitives/status-pill"
import { PageHeader } from "@/components/layout/page-header"
import { AccessDenied } from "@/components/states/access-denied"
import { EmptyState } from "@/components/states/empty-state"
import { SkeletonChart, SkeletonPanel, SkeletonTable } from "@/components/states/page-skeleton"
import { QueryRegion } from "@/components/states/query-boundary"

const MONTH_OPTIONS = ["6", "12", "24"] as const
const WINDOW_OPTIONS = ["30", "60", "90"] as const

function SignalCell({ value }: { value: number | null }) {
  return value === null ? <span className="text-muted-foreground">n/a</span> : <span>{formatInt(value)}</span>
}

function dueText(item: MaintenanceCalendarItem): string {
  if (item.due_date) return `Due ${formatDate(item.due_date)}`
  if (item.due_km !== null) return `Due at ${formatInt(item.due_km)} km`
  return "—"
}

export default function InsightsPage() {
  const { role } = useCurrentUser()
  const canRead = Boolean(role && can(role, "dashboard:read"))

  const [months, setMonths] = useState<(typeof MONTH_OPTIONS)[number]>("24")
  const [windowDays, setWindowDays] = useState<(typeof WINDOW_OPTIONS)[number]>("30")
  const [nlQuery, setNlQuery] = useState("")

  const fuelTrendsQuery = useFuelTrends(Number(months))
  const calendarQuery = useMaintenanceCalendar(Number(windowDays))
  const fleetHealthQuery = useFleetHealth({ enabled: canRead })

  if (!canRead) {
    return (
      <div className="space-y-6">
        <PageHeader crumbs={[{ label: "Insights" }]} />
        <AccessDenied area="insights" allowedRoles={["admin", "fleet_manager"]} />
      </div>
    )
  }

  const healthColumns: DataTableColumn<VehicleHealthScore>[] = [
    {
      key: "plate",
      header: "Vehicle",
      cell: (row) => (
        <Link href={`/foundation/vehicles/${row.vehicle_id}`} className="font-medium text-foreground hover:underline">
          {row.plate_number}
        </Link>
      ),
    },
    {
      key: "health",
      header: "Health",
      cell: (row) => {
        const { label, tone } = healthScoreLabel(row.health_score)
        return (
          <div className="flex items-center gap-2">
            <HealthGauge score={row.health_score} size="sm" />
            <StatusPill tone={tone}>{label}</StatusPill>
          </div>
        )
      },
    },
    { key: "compliance", header: "Compliance", align: "right", cell: (row) => <SignalCell value={row.signals.compliance} /> },
    { key: "incidents", header: "Incidents", align: "right", cell: (row) => <SignalCell value={row.signals.incidents} /> },
    { key: "maintenance", header: "Maintenance", align: "right", cell: (row) => <SignalCell value={row.signals.maintenance_currency} /> },
    { key: "fuel", header: "Fuel efficiency", align: "right", cell: (row) => <SignalCell value={row.signals.fuel_efficiency} /> },
  ]

  return (
    <div className="space-y-6">
      <PageHeader crumbs={[{ label: "Insights" }]} />

      <SectionPanel icon={Search} title="Ask a question">
        <div className="flex flex-col gap-3 sm:flex-row">
          <Input
            placeholder="e.g. Which vehicles are due for service this month?"
            value={nlQuery}
            onChange={(e) => setNlQuery(e.target.value)}
            className="flex-1"
          />
          <Button asChild variant="outline">
            <Link href="/chat">Ask in AI Assistant</Link>
          </Button>
        </div>
        <p className="text-caption text-muted-foreground">Natural-language questions are coming soon — this box doesn&apos;t send anything yet.</p>
      </SectionPanel>

      <SectionPanel
        icon={ChartLine}
        title="Fuel cost trend"
        action={
          <ToggleGroup type="single" value={months} onValueChange={(v) => v && setMonths(v as (typeof MONTH_OPTIONS)[number])}>
            {MONTH_OPTIONS.map((m) => (
              <ToggleGroupItem key={m} value={m} aria-label={`Last ${m} months`}>
                {m}mo
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        }
      >
        <QueryRegion
          query={fuelTrendsQuery}
          skeleton={<SkeletonChart />}
          empty={<EmptyState icon={ChartLine} title="No fuel data yet" description="Fuel costs will chart here once logs are recorded." />}
          isEmpty={(trends) => trends.length === 0}
          areaLabel="the fuel trend"
        >
          {(trends) => {
            const hasEfficiency = trends.some((t) => t.avg_cost_per_km !== null)
            const points = trends.map((t) => ({
              month: t.month,
              totalCost: parseDecimal(t.total_cost),
              avgCostPerKm: t.avg_cost_per_km !== null ? parseDecimal(t.avg_cost_per_km) : null,
            }))
            return (
              <AreaTrendChart
                data={points}
                xKey="month"
                xFormatter={formatMonthLabel}
                series={[
                  { key: "totalCost", label: "Fuel cost", color: "var(--chart-1)", valueFormatter: (v) => formatMoneyValue(v) },
                  ...(hasEfficiency
                    ? [{ key: "avgCostPerKm" as const, label: "Cost/km", color: "var(--chart-2)", axis: "right" as const, valueFormatter: (v: number) => formatNumberValue(v) }]
                    : []),
                ]}
              />
            )
          }}
        </QueryRegion>
      </SectionPanel>

      <SectionPanel
        icon={ListChecks}
        title="Maintenance calendar"
        action={
          <ToggleGroup type="single" value={windowDays} onValueChange={(v) => v && setWindowDays(v as (typeof WINDOW_OPTIONS)[number])}>
            {WINDOW_OPTIONS.map((w) => (
              <ToggleGroupItem key={w} value={w} aria-label={`Next ${w} days`}>
                {w}d
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        }
      >
        <QueryRegion
          query={calendarQuery}
          skeleton={<SkeletonPanel />}
          empty={<EmptyState icon={ListChecks} title="Nothing due" description={`No service is due in the next ${windowDays} days.`} />}
          isEmpty={(items) => items.length === 0}
          areaLabel="the maintenance calendar"
        >
          {(items) => {
            const sorted = [...items].sort((a, b) => (a.status === "overdue" ? 0 : 1) - (b.status === "overdue" ? 0 : 1))
            return (
              <div className="space-y-2">
                {sorted.map((item) => (
                  <DueRow
                    key={`${item.vehicle_id}-${item.service_type}`}
                    icon={ListChecks}
                    title={item.plate_number}
                    dueText={dueText(item)}
                    status={item.status}
                    href={`/foundation/vehicles/${item.vehicle_id}`}
                  />
                ))}
              </div>
            )
          }}
        </QueryRegion>
      </SectionPanel>

      <SectionPanel icon={ShieldAlert} title="Fleet health">
        <QueryRegion
          query={fleetHealthQuery}
          skeleton={<SkeletonTable rows={5} columns={6} />}
          empty={<EmptyState icon={ShieldAlert} title="No vehicles yet" description="Fleet health appears once vehicles are added." />}
          isEmpty={(rows) => rows.length === 0}
          areaLabel="fleet health"
        >
          {(rows) => {
            const sorted = [...rows].sort((a, b) => a.health_score - b.health_score)
            return (
              <>
                <DataTable columns={healthColumns} rows={sorted} getRowId={(row) => row.vehicle_id} />
                <p className="mt-2 text-caption text-muted-foreground">Retired vehicles aren&apos;t scored and don&apos;t appear here.</p>
              </>
            )
          }}
        </QueryRegion>
      </SectionPanel>
    </div>
  )
}
