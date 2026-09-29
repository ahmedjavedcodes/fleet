"use client"

import { useState } from "react"
import { Building2, Plus } from "lucide-react"
import { useSuppliers } from "@/lib/api/suppliers"
import { formatNumber } from "@/lib/api/decimal"
import { can } from "@/lib/rbac"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import type { Supplier } from "@/lib/schemas/supplier"
import { SUPPLIER_CATEGORY_LABELS } from "@/lib/enum-labels"
import { Button } from "@/components/ui/button"
import { DataTable, type DataTableColumn } from "@/components/primitives/data-table"
import { PageHeader } from "@/components/layout/page-header"
import { EmptyState } from "@/components/states/empty-state"
import { PageSkeleton } from "@/components/states/page-skeleton"
import { QueryRegion } from "@/components/states/query-boundary"
import { SupplierFormDialog } from "./_components/supplier-form-dialog"

export default function SuppliersPage() {
  const { role } = useCurrentUser()
  const suppliersQuery = useSuppliers("reliability_score")
  const canWrite = Boolean(role && can(role, "supplier:write"))

  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<Supplier | undefined>(undefined)

  const columns: DataTableColumn<Supplier>[] = [
    {
      key: "name",
      header: "Name",
      cell: (row) =>
        canWrite ? (
          <button
            className="font-semibold text-foreground hover:underline"
            onClick={() => {
              setEditing(row)
              setFormOpen(true)
            }}
          >
            {row.name}
          </button>
        ) : (
          <span className="font-semibold text-foreground">{row.name}</span>
        ),
    },
    { key: "category", header: "Category", cell: (row) => SUPPLIER_CATEGORY_LABELS[row.category] },
    { key: "address", header: "Address", cell: (row) => row.address ?? "—" },
    { key: "email", header: "Contact email", cell: (row) => row.contact_email ?? "—" },
    { key: "phone", header: "Phone", cell: (row) => row.phone ?? "—" },
    { key: "lead_time", header: "Avg lead time", align: "right", cell: (row) => (row.avg_lead_time_days ? `${row.avg_lead_time_days} days` : "—") },
    { key: "reliability", header: "Reliability", align: "right", cell: (row) => (row.reliability_score ? formatNumber(row.reliability_score, 1) : "—") },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        crumbs={[{ label: "Fleet" }, { label: "Suppliers" }]}
        actions={
          canWrite ? (
            <Button
              onClick={() => {
                setEditing(undefined)
                setFormOpen(true)
              }}
            >
              <Plus className="size-4" />
              Add supplier
            </Button>
          ) : undefined
        }
      />

      <QueryRegion
        query={suppliersQuery}
        skeleton={<PageSkeleton />}
        empty={
          <EmptyState icon={Building2} title="No suppliers yet" description={canWrite ? "Add your first supplier to get started." : "No suppliers have been added yet."} />
        }
        isEmpty={(suppliers) => suppliers.length === 0}
        areaLabel="suppliers"
      >
        {(suppliers) => <DataTable columns={columns} rows={suppliers} getRowId={(row) => row.id} />}
      </QueryRegion>

      <SupplierFormDialog open={formOpen} onOpenChange={setFormOpen} supplier={editing} />
    </div>
  )
}
