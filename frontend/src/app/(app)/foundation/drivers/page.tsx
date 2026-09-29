"use client"

import { useState } from "react"
import { Plus, Users } from "lucide-react"
import Link from "next/link"
import { toast } from "sonner"
import { useDeleteDriver, useDrivers } from "@/lib/api/drivers"
import { isApiError } from "@/lib/api/errors"
import { formatDate } from "@/lib/format-date"
import { can } from "@/lib/rbac"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import type { Driver } from "@/lib/schemas/driver"
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
import { MoreHorizontal } from "lucide-react"
import { DataTable, type DataTableColumn } from "@/components/primitives/data-table"
import { StatusPill } from "@/components/primitives/status-pill"
import { PageHeader } from "@/components/layout/page-header"
import { EmptyState } from "@/components/states/empty-state"
import { PageSkeleton } from "@/components/states/page-skeleton"
import { QueryRegion } from "@/components/states/query-boundary"
import { DriverFormDialog } from "./_components/driver-form-dialog"

function expiryTone(expiry: string): "destructive" | "warning" | "neutral" {
  const days = (new Date(expiry).getTime() - Date.now()) / 86_400_000
  if (days < 0) return "destructive"
  if (days <= 30) return "warning"
  return "neutral"
}

export default function DriversPage() {
  const { role } = useCurrentUser()
  const driversQuery = useDrivers()
  const deleteMutation = useDeleteDriver()
  const canWrite = Boolean(role && can(role, "driver:write"))

  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<Driver | undefined>(undefined)
  const [deleting, setDeleting] = useState<Driver | undefined>(undefined)

  function confirmDelete() {
    if (!deleting) return
    deleteMutation.mutate(deleting.id, {
      onSuccess: () => {
        toast.success("Driver deleted")
        setDeleting(undefined)
      },
      onError: (error) => {
        toast.error(isApiError(error) && "message" in error ? error.message : "Couldn't delete this driver.")
        setDeleting(undefined)
      },
    })
  }

  const columns: DataTableColumn<Driver>[] = [
    {
      key: "name",
      header: "Name",
      cell: (row) => (
        <Link href={`/foundation/drivers/${row.id}`} className="font-semibold text-foreground hover:underline">
          {row.full_name}
        </Link>
      ),
    },
    { key: "license", header: "License number", cell: (row) => row.license_number },
    { key: "license_type", header: "License Type", cell: (row) => row.license_type ?? "—" },
    { key: "license_issued", header: "Issued", cell: (row) => (row.license_issue_date ? formatDate(row.license_issue_date) : "—") },
    {
      key: "expiry",
      header: "License expiry",
      cell: (row) => <StatusPill tone={expiryTone(row.license_expiry)}>{formatDate(row.license_expiry)}</StatusPill>,
    },
    { key: "phone", header: "Phone", cell: (row) => row.phone },
    { key: "license_status", header: "License status", cell: (row) => row.license_current_status ?? "—" },
    {
      key: "status",
      header: "Status",
      cell: (row) => <StatusPill tone={row.status === "active" ? "success" : "neutral"}>{row.status[0]!.toUpperCase() + row.status.slice(1)}</StatusPill>,
    },
  ]
  if (canWrite) {
    columns.push({
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
            <DropdownMenuItem
              onSelect={() => {
                setEditing(row)
                setFormOpen(true)
              }}
            >
              Edit
            </DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onSelect={() => setDeleting(row)}>
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ),
    })
  }

  return (
    <div className="space-y-6">
      <PageHeader
        crumbs={[{ label: "Fleet" }, { label: "Drivers" }]}
        actions={
          canWrite ? (
            <Button
              onClick={() => {
                setEditing(undefined)
                setFormOpen(true)
              }}
            >
              <Plus className="size-4" />
              Add driver
            </Button>
          ) : undefined
        }
      />

      <QueryRegion
        query={driversQuery}
        skeleton={<PageSkeleton />}
        empty={<EmptyState icon={Users} title="No drivers yet" description={canWrite ? "Add your first driver to get started." : "No drivers have been added yet."} />}
        isEmpty={(drivers) => drivers.length === 0}
        areaLabel="drivers"
      >
        {(drivers) => <DataTable columns={columns} rows={drivers} getRowId={(row) => row.id} />}
      </QueryRegion>

      <DriverFormDialog open={formOpen} onOpenChange={setFormOpen} driver={editing} />

      <AlertDialog open={Boolean(deleting)} onOpenChange={(open) => !open && setDeleting(undefined)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {deleting?.full_name}?</AlertDialogTitle>
            <AlertDialogDescription>This removes the driver from active lists. This can&apos;t be undone from here.</AlertDialogDescription>
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
