"use client"

import { useState } from "react"
import { Fuel as FuelIcon, Plus, Route } from "lucide-react"
import { useFuelLogs, useFuelSummary } from "@/lib/api/fuel"
import { useTrips } from "@/lib/api/trips"
import { formatInt, formatMoney, formatNumber, formatRate } from "@/lib/api/decimal"
import { formatDate, formatDateTime, formatDurationBetween } from "@/lib/format-date"
import { can } from "@/lib/rbac"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import type { FuelLog } from "@/lib/schemas/fuel"
import type { TripLog } from "@/lib/schemas/trip"
import { inDateRange, matchesSearch } from "@/lib/table-filters"
import { Button } from "@/components/ui/button"
import { VehicleLink } from "@/components/fleet/vehicle-link"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { DataTable, type DataTableColumn } from "@/components/primitives/data-table"
import { FilterBar } from "@/components/primitives/filter-bar"
import { KpiTile } from "@/components/primitives/kpi-tile"
import { SectionPanel } from "@/components/primitives/section-panel"
import { StatusPill } from "@/components/primitives/status-pill"
import { PageHeader } from "@/components/layout/page-header"
import { EmptyState } from "@/components/states/empty-state"
import { PageSkeleton } from "@/components/states/page-skeleton"
import { QueryRegion } from "@/components/states/query-boundary"
import { FuelLogFormDialog } from "./_components/fuel-log-form-dialog"
import { TripFormDialog } from "./_components/trip-form-dialog"

function SlipCell({ slipId, poNumber }: { slipId: string | null; poNumber: string | null }) {
  if (!slipId && !poNumber) return <>—</>
  return (
    <div>
      {slipId ? <p>{slipId}</p> : null}
      {poNumber ? <p className="text-caption text-muted-foreground">PO {poNumber}</p> : null}
    </div>
  )
}

function PaymentCell({ method, card }: { method: string | null; card: string | null }) {
  if (!method && !card) return <>—</>
  return (
    <div>
      {method ? <p>{method}</p> : null}
      {card ? <p className="text-caption text-muted-foreground">{card}</p> : null}
    </div>
  )
}

function todayMonth(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`
}

export default function FuelPage() {
  const { role } = useCurrentUser()
  const canWriteFuel = Boolean(role && can(role, "fuel:write"))
  const canWriteTrip = Boolean(role && can(role, "trip:write"))
  const canSeeSummary = Boolean(role && can(role, "fuel:summary"))

  const [fuelFormOpen, setFuelFormOpen] = useState(false)
  const [tripFormOpen, setTripFormOpen] = useState(false)
  const [search, setSearch] = useState("")
  const [range, setRange] = useState({ from: "", to: "" })

  // Fuel dates are filtered by the server (the list is capped at 50 rows, so a client-side
  // filter would only ever see the first page); trips are few, so they filter locally.
  const fuelLogsQuery = useFuelLogs({ limit: 50, date_from: range.from || undefined, date_to: range.to || undefined })
  const tripsQuery = useTrips()
  const summaryQuery = useFuelSummary(todayMonth(), { enabled: canSeeSummary })

  const fuelColumns: DataTableColumn<FuelLog>[] = [
    { key: "date", header: "Date", cell: (r) => formatDate(r.date) },
    { key: "vehicle", header: "Vehicle", cell: (r) => <VehicleLink vehicleId={r.vehicle_id} plate={r.vehicle_plate} name={r.vehicle_name} /> },
    { key: "driver", header: "Driver", cell: (r) => r.driver_name ?? "—" },
    { key: "slip", header: "Slip / PO", cell: (r) => <SlipCell slipId={r.slip_id} poNumber={r.po_number} /> },
    { key: "station", header: "Station", cell: (r) => r.fuel_station_name ?? "—" },
    { key: "payment", header: "Payment", cell: (r) => <PaymentCell method={r.payment_method} card={r.card_used} /> },
    { key: "odometer", header: "Odometer", align: "right", cell: (r) => formatInt(r.odometer_reading) },
    { key: "liters", header: "Liters", align: "right", cell: (r) => formatNumber(r.liters_filled) },
    { key: "price", header: "Price/L", align: "right", cell: (r) => formatRate(r.price_per_liter) },
    { key: "total", header: "Total", align: "right", cell: (r) => formatMoney(r.total_cost) },
    { key: "cost_per_km", header: "Cost/km", align: "right", cell: (r) => (r.cost_per_km ? formatRate(r.cost_per_km) : "—") },
    {
      key: "anomaly",
      header: "",
      cell: (r) => (r.is_anomalous ? <StatusPill tone="warning">Anomaly</StatusPill> : null),
    },
  ]

  const tripColumns: DataTableColumn<TripLog>[] = [
    { key: "date", header: "Date", cell: (r) => formatDate(r.start_time.slice(0, 10)) },
    { key: "vehicle_name", header: "Vehicle Name", cell: (r) => r.vehicle_name ?? "—" },
    { key: "vehicle_plate", header: "Vehicle Plate", cell: (r) => <VehicleLink vehicleId={r.vehicle_id} plate={r.vehicle_plate} /> },
    { key: "driver", header: "Driver", cell: (r) => r.driver_name ?? "—" },
    { key: "start", header: "Started", cell: (r) => formatDateTime(r.start_time) },
    { key: "start_odometer", header: "Start Odometer", align: "right", cell: (r) => formatInt(r.start_odometer) },
    { key: "end_odometer", header: "End Odometer", align: "right", cell: (r) => formatInt(r.end_odometer) },
    { key: "distance", header: "Distance (km)", align: "right", cell: (r) => formatInt(r.distance_km) },
    { key: "duration", header: "Duration", cell: (r) => formatDurationBetween(r.start_time, r.end_time) },
    { key: "fuel", header: "Fuel used (L)", align: "right", cell: (r) => (r.fuel_consumed ? formatNumber(r.fuel_consumed) : "—") },
  ]

  const filterBar = (
    <FilterBar
      search={search}
      onSearchChange={setSearch}
      searchLabel="Search fuel and trips"
      searchPlaceholder="Search vehicle or driver…"
      dateRange={{ from: range.from, to: range.to, onChange: setRange }}
    />
  )

  return (
    <div className="space-y-6">
      <PageHeader crumbs={[{ label: "Operations" }, { label: "Fuel & Trips" }]} />

      <Tabs defaultValue="fuel">
        <TabsList>
          <TabsTrigger value="fuel">Fuel logs</TabsTrigger>
          <TabsTrigger value="trips">Trips</TabsTrigger>
          {canSeeSummary ? <TabsTrigger value="summary">Summary</TabsTrigger> : null}
        </TabsList>

        <TabsContent value="fuel" className="space-y-4">
          <div className="flex justify-end">
            {canWriteFuel ? (
              <Button onClick={() => setFuelFormOpen(true)}>
                <Plus className="size-4" />
                Log fuel
              </Button>
            ) : null}
          </div>
          {filterBar}
          <QueryRegion
            query={fuelLogsQuery}
            skeleton={<PageSkeleton />}
            empty={
              <EmptyState
                icon={FuelIcon}
                title={range.from || range.to ? "No matches" : "No fuel logs yet"}
                description={range.from || range.to ? "No fuel logs fall in this date range." : "Fuel logs will appear here once recorded."}
              />
            }
            isEmpty={(rows) => rows.length === 0}
            areaLabel="fuel logs"
          >
            {(rows) => {
              const filtered = rows.filter((r) => matchesSearch(search, r.vehicle_plate, r.vehicle_name, r.driver_name))
              return filtered.length === 0 ? (
                <EmptyState icon={FuelIcon} title="No matches" description="No fuel logs match your search or dates." />
              ) : (
                <DataTable columns={fuelColumns} rows={filtered} getRowId={(r) => r.id} />
              )
            }}
          </QueryRegion>
        </TabsContent>

        <TabsContent value="trips" className="space-y-4">
          <div className="flex justify-end">
            {canWriteTrip ? (
              <Button onClick={() => setTripFormOpen(true)}>
                <Plus className="size-4" />
                Log trip
              </Button>
            ) : null}
          </div>
          {filterBar}
          <QueryRegion
            query={tripsQuery}
            skeleton={<PageSkeleton />}
            empty={<EmptyState icon={Route} title="No trips yet" description="Trips will appear here once logged." />}
            isEmpty={(rows) => rows.length === 0}
            areaLabel="trips"
          >
            {(rows) => {
              const filtered = rows.filter(
                (r) =>
                  matchesSearch(search, r.vehicle_plate, r.vehicle_name, r.driver_name) &&
                  inDateRange(r.start_time, range.from, range.to)
              )
              return filtered.length === 0 ? (
                <EmptyState icon={Route} title="No matches" description="No trips match your search or dates." />
              ) : (
                <DataTable columns={tripColumns} rows={filtered} getRowId={(r) => r.id} />
              )
            }}
          </QueryRegion>
        </TabsContent>

        {canSeeSummary ? (
          <TabsContent value="summary" className="space-y-4">
            <QueryRegion query={summaryQuery} skeleton={<PageSkeleton />} areaLabel="the fuel summary">
              {(summary) => (
                <div className="space-y-4">
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <KpiTile icon={FuelIcon} tone="green" label="Total cost" value={summary.total_cost} format="money" />
                    <KpiTile icon={FuelIcon} tone="blue" label="Total liters" value={summary.total_liters} format="number" />
                    <KpiTile
                      icon={FuelIcon}
                      tone="purple"
                      label="Avg cost/km"
                      value={summary.avg_cost_per_km ?? "0"}
                      format="money"
                      hint={!summary.avg_cost_per_km ? "No data yet" : undefined}
                    />
                  </div>
                  <SectionPanel icon={FuelIcon} title="By vehicle">
                    {summary.by_vehicle.length === 0 ? (
                      <EmptyState icon={FuelIcon} title="No fuel data yet" description="Per-vehicle costs will appear here once logged." />
                    ) : (
                      <DataTable
                        columns={[
                          {
                            key: "vehicle",
                            header: "Vehicle",
                            cell: (r) => <VehicleLink vehicleId={r.vehicle_id} plate={r.plate_number} name={r.vehicle_name} />,
                          },
                          { key: "drivers", header: "Drivers", cell: (r) => (r.driver_names.length ? r.driver_names.join(", ") : "—") },
                          { key: "fills", header: "Fills", align: "right", cell: (r) => r.fill_count },
                          {
                            key: "last_fill",
                            header: "Last fill",
                            cell: (r) => (r.last_fill_date ? formatDate(r.last_fill_date) : "—"),
                          },
                          { key: "cost", header: "Cost", align: "right", cell: (r) => formatMoney(r.total_cost) },
                          { key: "liters", header: "Liters", align: "right", cell: (r) => formatNumber(r.total_liters) },
                          { key: "avg", header: "Avg cost/km", align: "right", cell: (r) => (r.avg_cost_per_km ? formatRate(r.avg_cost_per_km) : "—") },
                        ]}
                        rows={summary.by_vehicle}
                        getRowId={(r) => r.vehicle_id}
                      />
                    )}
                  </SectionPanel>
                </div>
              )}
            </QueryRegion>
          </TabsContent>
        ) : null}
      </Tabs>

      <FuelLogFormDialog open={fuelFormOpen} onOpenChange={setFuelFormOpen} />
      <TripFormDialog open={tripFormOpen} onOpenChange={setTripFormOpen} />
    </div>
  )
}
