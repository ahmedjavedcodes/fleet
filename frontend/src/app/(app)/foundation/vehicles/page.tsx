"use client"

import { useMemo, useState } from "react"
import { MoreHorizontal, Plus, Truck } from "lucide-react"
import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { toast } from "sonner"
import { useDeleteVehicle, useVehicles } from "@/lib/api/vehicles"
import { isApiError } from "@/lib/api/errors"
import { formatInt } from "@/lib/api/decimal"
import { can } from "@/lib/rbac"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import type { Vehicle } from "@/lib/schemas/vehicle"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { DataTable, type DataTableColumn } from "@/components/primitives/data-table"
import { StatusPill, type StatusPillTone } from "@/components/primitives/status-pill"
import { PageHeader } from "@/components/layout/page-header"
import { EmptyState } from "@/components/states/empty-state"
import { PageSkeleton } from "@/components/states/page-skeleton"
import { QueryRegion } from "@/components/states/query-boundary"
import { VehicleFormDialog } from "./_components/vehicle-form-dialog"

const STATUS_LABEL: Record<Vehicle["status"], { label: string; tone: StatusPillTone }> = {
  active: { label: "Active", tone: "success" },
  maintenance: { label: "In maintenance", tone: "warning" },
  retired: { label: "Retired", tone: "neutral" },
}

export default function VehiclesPage() {
  const { role } = useCurrentUser()
  const searchParams = useSearchParams()
  const vehiclesQuery = useVehicles()
  const deleteMutation = useDeleteVehicle()

  const [search, setSearch] = useState("")
  const [statusFilter, setStatusFilter] = useState<Vehicle["status"] | "all">("all")
  const [formOpen, setFormOpen] = useState(searchParams.get("new") === "1")
  const [editing, setEditing] = useState<Vehicle | undefined>(undefined)
  const [deleting, setDeleting] = useState<Vehicle | undefined>(undefined)

  const canWrite = Boolean(role && can(role, "vehicle:write"))

  function openCreate() {
    setEditing(undefined)
    setFormOpen(true)
  }
  function openEdit(vehicle: Vehicle) {
    setEditing(vehicle)
    setFormOpen(true)
  }

  function confirmDelete() {
    if (!deleting) return
    deleteMutation.mutate(deleting.id, {
      onSuccess: () => {
        toast.success("Vehicle deleted")
        setDeleting(undefined)
      },
      onError: (error) => {
        toast.error(isApiError(error) && "message" in error ? error.message : "Couldn't delete this vehicle.")
        setDeleting(undefined)
      },
    })
  }

  const columns: DataTableColumn<Vehicle>[] = useMemo(() => {
    const base: DataTableColumn<Vehicle>[] = [
      {
        key: "plate",
        header: "Plate",
        cell: (row) => (
          <Link href={`/foundation/vehicles/${row.id}`} className="font-semibold text-foreground hover:underline">
            {row.plate_number}
          </Link>
        ),
      },
      { key: "make_model", header: "Make & model", cell: (row) => `${row.make} ${row.model}` },
      { key: "year", header: "Year", cell: (row) => row.year },
      { key: "fuel_type", header: "Fuel type", cell: (row) => row.fuel_type[0]!.toUpperCase() + row.fuel_type.slice(1) },
      {
        key: "status",
        header: "Status",
        cell: (row) => {
          const s = STATUS_LABEL[row.status]
          return <StatusPill tone={s.tone}>{s.label}</StatusPill>
        },
      },
      { key: "odometer", header: "Odometer", align: "right", cell: (row) => `${formatInt(row.current_odometer)} km` },
    ]
    if (canWrite) {
      base.push({
        key: "actions",
        header: "",
        align: "right",
        cell: (row) => (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" onClick={(e) => e.stopPropagation()}>
                <MoreHorizontal className="size-4" />
                <span className="sr-only">Actions</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => openEdit(row)}>Edit</DropdownMenuItem>
              <DropdownMenuItem variant="destructive" onSelect={() => setDeleting(row)}>
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ),
      })
    }
    return base
  }, [canWrite])

  return (
    <div className="space-y-6">
      <PageHeader
        crumbs={[{ label: "Fleet" }, { label: "Vehicles" }]}
        actions={
          canWrite ? (
            <Button onClick={openCreate}>
              <Plus className="size-4" />
              Add vehicle
            </Button>
          ) : undefined
        }
      />

      <QueryRegion
        query={vehiclesQuery}
        skeleton={<PageSkeleton />}
        empty={
          <EmptyState
            icon={Truck}
            title="No vehicles yet"
            description={canWrite ? "Add your first vehicle to get started." : "No vehicles have been added yet."}
            action={
              canWrite ? (
                <Button onClick={openCreate}>
                  <Plus className="size-4" />
                  Add your first vehicle
                </Button>
              ) : undefined
            }
          />
        }
        isEmpty={(vehicles) => vehicles.length === 0}
        areaLabel="vehicles"
      >
        {(vehicles) => {
          const filtered = vehicles.filter((v) => {
            const matchesStatus = statusFilter === "all" || v.status === statusFilter
            const q = search.trim().toLowerCase()
            const matchesSearch =
              q === "" || v.plate_number.toLowerCase().includes(q) || v.make.toLowerCase().includes(q) || v.model.toLowerCase().includes(q)
            return matchesStatus && matchesSearch
          })
          return (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <Input
                  placeholder="Search plate, make or model…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="max-w-xs"
                />
                <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as typeof statusFilter)}>
                  <SelectTrigger className="w-40">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All statuses</SelectItem>
                    <SelectItem value="active">Active</SelectItem>
                    <SelectItem value="maintenance">In maintenance</SelectItem>
                    <SelectItem value="retired">Retired</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {filtered.length === 0 ? (
                <EmptyState icon={Truck} title="No matches" description="No vehicles match your search or filter." />
              ) : (
                <DataTable columns={columns} rows={filtered} getRowId={(row) => row.id} />
              )}
            </div>
          )
        }}
      </QueryRegion>

      <VehicleFormDialog open={formOpen} onOpenChange={setFormOpen} vehicle={editing} />

      <AlertDialog open={Boolean(deleting)} onOpenChange={(open) => !open && setDeleting(undefined)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {deleting?.plate_number}?</AlertDialogTitle>
            <AlertDialogDescription>This removes the vehicle from active lists. This can&apos;t be undone from here.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
