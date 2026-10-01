"use client"

import { useState } from "react"
import { ClipboardList, Plus, ShieldAlert } from "lucide-react"
import { useSearchParams } from "next/navigation"
import { useIncidents } from "@/lib/api/incidents"
import { useDriverReports } from "@/lib/api/driver-reports"
import { resolveAttachmentUrl } from "@/lib/api/uploads"
import { formatMoney } from "@/lib/api/decimal"
import { formatDate, formatDateTime } from "@/lib/format-date"
import { INCIDENT_RESOLUTION_LABELS, INCIDENT_SEVERITY_LABELS, INCIDENT_SEVERITY_TONE, INCIDENT_TYPE_LABELS, VEHICLE_CONDITION_LABELS } from "@/lib/enum-labels"
import { can } from "@/lib/rbac"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import type { IncidentLog } from "@/lib/schemas/incident"
import { ALL, inDateRange, matchesSearch } from "@/lib/table-filters"
import type { DriverReport } from "@/lib/schemas/driver-report"
import { Button } from "@/components/ui/button"
import { VehicleLink } from "@/components/fleet/vehicle-link"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { DataTable, type DataTableColumn } from "@/components/primitives/data-table"
import { FilterBar } from "@/components/primitives/filter-bar"
import { StatusPill } from "@/components/primitives/status-pill"
import { PageHeader } from "@/components/layout/page-header"
import { EmptyState } from "@/components/states/empty-state"
import { PageSkeleton } from "@/components/states/page-skeleton"
import { QueryRegion } from "@/components/states/query-boundary"
import { IncidentFormDialog } from "./_components/incident-form-dialog"
import { ResolveIncidentDialog } from "./_components/resolve-incident-dialog"
import { ShiftReportFormDialog } from "./_components/shift-report-form-dialog"

export default function AccountabilityPage() {
  const { role } = useCurrentUser()
  const searchParams = useSearchParams()
  const vehicleId = searchParams.get("vehicle_id") ?? undefined
  // Arriving from a notification: show just that incident.
  const incidentId = searchParams.get("incident") ?? undefined

  const canCreateIncident = Boolean(role && can(role, "incident:create"))
  const canResolveIncident = Boolean(role && can(role, "incident:resolve"))
  const canWriteReport = Boolean(role && can(role, "driver-report:write"))

  const [incidentFormOpen, setIncidentFormOpen] = useState(searchParams.get("new") === "1")
  const [reportFormOpen, setReportFormOpen] = useState(false)
  const [resolving, setResolving] = useState<IncidentLog | undefined>(undefined)
  const [search, setSearch] = useState("")
  const [severity, setSeverity] = useState(ALL)
  const [resolution, setResolution] = useState(ALL)
  const [reportSearch, setReportSearch] = useState("")
  const [reportRange, setReportRange] = useState({ from: "", to: "" })

  const incidentsQuery = useIncidents()
  const reportsQuery = useDriverReports()

  const incidentColumns: DataTableColumn<IncidentLog>[] = [
    { key: "date", header: "When", cell: (r) => (r.incident_time ? formatDateTime(r.incident_time) : formatDate(r.date)) },
    { key: "vehicle", header: "Vehicle", cell: (r) => <VehicleLink vehicleId={r.vehicle_id} plate={r.vehicle_plate} name={r.vehicle_name} /> },
    { key: "driver", header: "Driver", cell: (r) => r.driver_name ?? "—" },
    { key: "type", header: "Type", cell: (r) => INCIDENT_TYPE_LABELS[r.incident_type] },
    { key: "severity", header: "Severity", cell: (r) => <StatusPill tone={INCIDENT_SEVERITY_TONE[r.severity]}>{r.severity[0]!.toUpperCase() + r.severity.slice(1)}</StatusPill> },
    { key: "description", header: "Description", cell: (r) => <span className="block max-w-xs truncate" title={r.description}>{r.description}</span> },
    { key: "area", header: "Location", cell: (r) => r.location_area ?? r.location_description ?? "—" },
    {
      key: "attachment",
      header: "",
      cell: (r) =>
        r.attachment_url ? (
          <a href={resolveAttachmentUrl(r.attachment_url)} target="_blank" rel="noreferrer" className="text-sm text-foreground underline">
            Attachment
          </a>
        ) : null,
    },
    { key: "cost", header: "Est. cost", align: "right", cell: (r) => (r.estimated_cost ? formatMoney(r.estimated_cost) : "—") },
    { key: "status", header: "Status", cell: (r) => <StatusPill tone={r.resolution_status === "open" ? "destructive" : r.resolution_status === "investigating" ? "warning" : "success"}>{INCIDENT_RESOLUTION_LABELS[r.resolution_status]}</StatusPill> },
  ]
  if (canResolveIncident) {
    incidentColumns.push({
      key: "actions",
      header: "",
      align: "right",
      cell: (r) => (
        <Button variant="outline" size="sm" onClick={(e) => { e.stopPropagation(); setResolving(r) }}>
          Update
        </Button>
      ),
    })
  }

  const reportColumns: DataTableColumn<DriverReport>[] = [
    { key: "date", header: "Shift date", cell: (r) => formatDate(r.shift_date) },
    { key: "vehicle", header: "Vehicle", cell: (r) => <VehicleLink vehicleId={r.vehicle_id} plate={r.vehicle_plate} name={r.vehicle_name} /> },
    { key: "driver", header: "Driver", cell: (r) => r.driver_name ?? "—" },
    { key: "condition", header: "Vehicle condition", cell: (r) => VEHICLE_CONDITION_LABELS[r.vehicle_condition] },
    { key: "handover", header: "Handover notes", cell: (r) => r.handover_notes ?? "—" },
    { key: "issues", header: "Issues reported", cell: (r) => r.issues_reported ?? "—" },
  ]

  return (
    <div className="space-y-6">
      <PageHeader crumbs={[{ label: "Operations" }, { label: "Accountability" }]} />

      <Tabs defaultValue="incidents">
        <TabsList>
          <TabsTrigger value="incidents">Incidents</TabsTrigger>
          <TabsTrigger value="reports">Shift reports</TabsTrigger>
        </TabsList>

        <TabsContent value="incidents" className="space-y-4">
          <div className="flex justify-end">
            {canCreateIncident ? (
              <Button onClick={() => setIncidentFormOpen(true)}>
                <Plus className="size-4" />
                Report incident
              </Button>
            ) : null}
          </div>
          <QueryRegion
            query={incidentsQuery}
            skeleton={<PageSkeleton />}
            empty={<EmptyState icon={ShieldAlert} title="No incidents reported" description="Incidents will appear here once reported." />}
            isEmpty={(rows) => rows.length === 0}
            areaLabel="incidents"
          >
            {(rows) => {
              const filtered = rows
                .filter(
                  (r) =>
                    (!incidentId || r.id === incidentId) &&
                    matchesSearch(search, r.vehicle_plate, r.vehicle_name, r.driver_name) &&
                    (severity === ALL || r.severity === severity) &&
                    (resolution === ALL || r.resolution_status === resolution)
                )
                .sort((a, b) => b.date.localeCompare(a.date))
              return (
                <div className="space-y-4">
                  <FilterBar
                    search={search}
                    onSearchChange={setSearch}
                    searchLabel="Search incidents"
                    searchPlaceholder="Search vehicle or driver…"
                    selects={[
                      {
                        label: "Filter by severity",
                        value: severity,
                        onChange: setSeverity,
                        allLabel: "All severities",
                        options: Object.entries(INCIDENT_SEVERITY_LABELS).map(([value, label]) => ({ value, label })),
                      },
                      {
                        label: "Filter by status",
                        value: resolution,
                        onChange: setResolution,
                        allLabel: "All statuses",
                        options: Object.entries(INCIDENT_RESOLUTION_LABELS).map(([value, label]) => ({ value, label })),
                      },
                    ]}
                  />
                  {filtered.length === 0 ? (
                    <EmptyState icon={ShieldAlert} title="No matches" description="No incidents match your search or filters." />
                  ) : (
                    <DataTable columns={incidentColumns} rows={filtered} getRowId={(r) => r.id} />
                  )}
                </div>
              )
            }}
          </QueryRegion>
        </TabsContent>

        <TabsContent value="reports" className="space-y-4">
          <div className="flex justify-end">
            {canWriteReport ? (
              <Button onClick={() => setReportFormOpen(true)}>
                <Plus className="size-4" />
                Submit shift report
              </Button>
            ) : null}
          </div>
          <QueryRegion
            query={reportsQuery}
            skeleton={<PageSkeleton />}
            empty={<EmptyState icon={ClipboardList} title="No shift reports yet" description="Shift handover reports will appear here." />}
            isEmpty={(rows) => rows.length === 0}
            areaLabel="shift reports"
          >
            {(rows) => {
              const filtered = rows
                .filter(
                  (r) =>
                    matchesSearch(reportSearch, r.vehicle_plate, r.vehicle_name, r.handover_notes, r.issues_reported) &&
                    inDateRange(r.shift_date, reportRange.from, reportRange.to)
                )
                .sort((a, b) => b.shift_date.localeCompare(a.shift_date))
              return (
                <div className="space-y-4">
                  <FilterBar
                    search={reportSearch}
                    onSearchChange={setReportSearch}
                    searchLabel="Search shift reports"
                    searchPlaceholder="Search vehicle or notes…"
                    dateRange={{ from: reportRange.from, to: reportRange.to, onChange: setReportRange }}
                  />
                  {filtered.length === 0 ? (
                    <EmptyState icon={ClipboardList} title="No matches" description="No shift reports match your search or dates." />
                  ) : (
                    <DataTable columns={reportColumns} rows={filtered} getRowId={(r) => r.id} />
                  )}
                </div>
              )
            }}
          </QueryRegion>
        </TabsContent>
      </Tabs>

      <IncidentFormDialog open={incidentFormOpen} onOpenChange={setIncidentFormOpen} defaultVehicleId={vehicleId} />
      <ShiftReportFormDialog open={reportFormOpen} onOpenChange={setReportFormOpen} />
      {resolving ? <ResolveIncidentDialog incident={resolving} onOpenChange={(open) => !open && setResolving(undefined)} /> : null}
    </div>
  )
}
