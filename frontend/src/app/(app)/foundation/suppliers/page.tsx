"use client"

import { useState } from "react"
import { Building2, Plus } from "lucide-react"
import { useSuppliers } from "@/lib/api/suppliers"
import { parseDecimal } from "@/lib/api/decimal"
import { can } from "@/lib/rbac"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import type { Supplier } from "@/lib/schemas/supplier"
import { ALL, matchesSearch } from "@/lib/table-filters"
import { SUPPLIER_CATEGORY_LABELS } from "@/lib/enum-labels"
import { Button } from "@/components/ui/button"
import { DataTable, type DataTableColumn } from "@/components/primitives/data-table"
import { FilterBar } from "@/components/primitives/filter-bar"
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
  const [search, setSearch] = useState("")
  const [category, setCategory] = useState(ALL)

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
    { key: "reliability", header: "Reliability", align: "right", cell: (row) => (row.reliability_score ? `${Math.round(parseDecimal(row.reliability_score) * 100)}%` : "—") },
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
        {(suppliers) => {
          const filtered = suppliers.filter((s) => matchesSearch(search, s.name) && (category === ALL || s.category === category))
          return (
            <div className="space-y-4">
              <FilterBar
                search={search}
                onSearchChange={setSearch}
                searchLabel="Search suppliers"
                searchPlaceholder="Search supplier name…"
                selects={[
                  {
                    label: "Filter by category",
                    value: category,
                    onChange: setCategory,
                    allLabel: "All categories",
                    options: Object.entries(SUPPLIER_CATEGORY_LABELS).map(([value, label]) => ({ value, label })),
                  },
                ]}
              />
              {filtered.length === 0 ? (
                <EmptyState icon={Building2} title="No matches" description="No suppliers match your search or filter." />
              ) : (
                <DataTable columns={columns} rows={filtered} getRowId={(row) => row.id} />
              )}
            </div>
          )
        }}
      </QueryRegion>

      <SupplierFormDialog open={formOpen} onOpenChange={setFormOpen} supplier={editing} />
    </div>
  )
}
