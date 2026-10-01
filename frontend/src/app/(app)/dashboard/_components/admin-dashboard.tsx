"use client"

import { useState } from "react"
import { Building2, ChartLine, Fuel, ListChecks, ShieldAlert, Truck, Users, Wrench } from "lucide-react"
import Link from "next/link"
import { useDashboardSummary, useFleetHealthPages, useFuelTrends, useMaintenanceCalendarPages } from "@/lib/api/dashboard"
import { formatInt, formatMoneyValue, formatNumberValue, parseDecimal } from "@/lib/api/decimal"
import { formatDate, formatMonthLabel } from "@/lib/format-date"
import { healthScoreLabel } from "@/lib/health-score"
import { can } from "@/lib/rbac"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import type { MaintenanceCalendarItem, VehicleHealthScore } from "@/lib/schemas/dashboard"
import { Button } from "@/components/ui/button"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { AreaTrendChart } from "@/components/charts/area-trend-chart"
import { HealthGauge } from "@/components/charts/health-gauge"
import { DueRow } from "@/components/fleet/due-row"
import { DataTable, type DataTableColumn } from "@/components/primitives/data-table"
import { KpiTile } from "@/components/primitives/kpi-tile"
import { SectionPanel } from "@/components/primitives/section-panel"
import { StatusPill } from "@/components/primitives/status-pill"
import { PageHeader } from "@/components/layout/page-header"
import { EmptyState } from "@/components/states/empty-state"
import { SkeletonChart, SkeletonKpiGrid, SkeletonPanel, SkeletonTable } from "@/components/states/page-skeleton"
import { QueryRegion } from "@/components/states/query-boundary"
import { Greeting } from "./greeting"

const MONTH_OPTIONS = ["6", "12", "24"] as const

// The lists below load a page at a time from the backend and render only what has been loaded.
function LoadMore({
  query,
  loaded,
  total,
  noun,
}: {
  query: { hasNextPage: boolean; isFetchingNextPage: boolean; fetchNextPage: () => unknown }
  loaded: number
  total: number | null
  noun: string
}) {
  if (!query.hasNextPage) return null
  return (
    <div className="mt-3 flex items-center justify-between gap-3 text-caption text-muted-foreground">
      <span>{total !== null ? `Showing ${formatInt(loaded)} of ${formatInt(total)} ${noun}` : `Showing ${formatInt(loaded)} ${noun}`}</span>
      <Button type="button" variant="outline" size="sm" disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>
        {query.isFetchingNextPage ? "Loading…" : "Load more"}
      </Button>
    </div>
  )
}

function SignalCell({ value }: { value: number | null }) {
  return value === null ? <span className="text-muted-foreground">n/a</span> : <span>{formatInt(value)}</span>
}

function dueText(item: MaintenanceCalendarItem): string {
  if (item.due_date) return `Due ${formatDate(item.due_date)}`
  if (item.due_km !== null) return `Due at ${formatInt(item.due_km)} km`
  return "—"
}

export function AdminDashboard() {
  const { role } = useCurrentUser()
  const [months, setMonths] = useState<(typeof MONTH_OPTIONS)[number]>("12")

  const summaryQuery = useDashboardSummary()
  const fuelTrendsQuery = useFuelTrends(Number(months))
  const calendarQuery = useMaintenanceCalendarPages(30)
  const fleetHealthQuery = useFleetHealthPages()

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
    {
      key: "maintenance",
      header: "Maintenance",
      align: "right",
      cell: (row) => <SignalCell value={row.signals.maintenance_currency} />,
    },
    {
      key: "fuel",
      header: "Fuel efficiency",
      align: "right",
      cell: (row) => <SignalCell value={row.signals.fuel_efficiency} />,
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        crumbs={[{ label: "Overview" }]}
        actions={
          role && can(role, "vehicle:write") ? (
            <Button asChild variant="outline">
              <Link href="/foundation/vehicles?new=1">Add vehicle</Link>
            </Button>
          ) : undefined
        }
      />
      <Greeting />

      <QueryRegion query={summaryQuery} skeleton={<SkeletonKpiGrid count={6} />} areaLabel="the dashboard summary">
        {(summary) => (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <KpiTile icon={Truck} tone="blue" label="Vehicles" value={String(summary.total_vehicles)} format="count" href="/foundation/vehicles" />
            <KpiTile
              icon={Users}
              tone="purple"
              label="Active drivers"
              value={String(summary.active_drivers)}
              format="count"
              href="/foundation/drivers"
            />
            <KpiTile icon={Fuel} tone="green" label="Fuel cost (month)" value={summary.month_fuel_cost} format="money" href="/fuel" />
            <KpiTile
              icon={Wrench}
              tone="amber"
              label="Overdue maintenance"
              value={String(summary.overdue_maintenance_count)}
              format="count"
              href="/maintenance"
            />
            <KpiTile
              icon={Building2}
              tone="blue"
              label="Active suppliers"
              value={String(summary.active_suppliers_count)}
              format="count"
              href="/foundation/suppliers"
            />
            <KpiTile
              icon={ShieldAlert}
              tone="destructive"
              label="Open incidents"
              value={String(summary.open_incidents_count)}
              format="count"
              href="/accountability"
              hint="Open & investigating"
            />
          </div>
        )}
      </QueryRegion>

      <div className="grid gap-4 lg:grid-cols-3">
        <SectionPanel
          icon={ChartLine}
          title="Fuel cost trend"
          className="lg:col-span-2"
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
                    {
                      key: "totalCost",
                      label: "Fuel cost",
                      color: "var(--chart-1)",
                      valueFormatter: (v) => formatMoneyValue(v),
                    },
                    ...(hasEfficiency
                      ? [
                          {
                            key: "avgCostPerKm" as const,
                            label: "Cost/km",
                            color: "var(--chart-2)",
                            axis: "right" as const,
                            valueFormatter: (v: number) => formatNumberValue(v),
                          },
                        ]
                      : []),
                  ]}
                />
              )
            }}
          </QueryRegion>
        </SectionPanel>

        <SectionPanel icon={ListChecks} title="Upcoming & overdue" action={<Link href="/maintenance" className="text-sm font-medium text-primary-strong hover:underline">View all</Link>}>
          <QueryRegion
            query={calendarQuery}
            skeleton={<SkeletonPanel />}
            empty={<EmptyState icon={ListChecks} title="Nothing due" description="No service is due in the next 30 days." />}
            isEmpty={(list) => list.items.length === 0}
            areaLabel="the maintenance calendar"
          >
            {(list) => (
              // Overdue first, then by due date: the backend orders and pages it.
              <div>
                <div className="space-y-2">
                  {list.items.map((item) => (
                    <DueRow
                      key={`${item.vehicle_id}-${item.service_type}`}
                      icon={Wrench}
                      title={item.plate_number}
                      dueText={dueText(item)}
                      status={item.status}
                      href={`/foundation/vehicles/${item.vehicle_id}`}
                    />
                  ))}
                </div>
                <LoadMore query={calendarQuery} loaded={list.items.length} total={list.total} noun="items" />
              </div>
            )}
          </QueryRegion>
        </SectionPanel>
      </div>

      <SectionPanel icon={ShieldAlert} title="Fleet health">
        <QueryRegion
          query={fleetHealthQuery}
          skeleton={<SkeletonTable rows={5} columns={6} />}
          empty={<EmptyState icon={Truck} title="No vehicles yet" description="Fleet health appears once vehicles are added." />}
          isEmpty={(list) => list.items.length === 0}
          areaLabel="fleet health"
        >
          {(list) => (
            // Worst health first: the backend sorts and pages it, so pages are loaded on request rather than all at once.
            <>
              <DataTable columns={healthColumns} rows={list.items} getRowId={(row) => row.vehicle_id} pageSize={1000} />
              <LoadMore query={fleetHealthQuery} loaded={list.items.length} total={list.total} noun="vehicles" />
              <p className="mt-2 text-caption text-muted-foreground">Retired vehicles aren&apos;t scored and don&apos;t appear here.</p>
            </>
          )}
        </QueryRegion>
      </SectionPanel>
    </div>
  )
}
