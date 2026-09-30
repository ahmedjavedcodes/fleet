"use client"

import { FileText } from "lucide-react"
import { formatDateTime } from "@/lib/format-date"
import { DOCUMENT_STATUS_TONE, DOCUMENT_TYPE_LABELS } from "@/lib/enum-labels"
import type { DocumentResponse } from "@/lib/schemas/document"
import { Button } from "@/components/ui/button"
import { DataTable, type DataTableColumn } from "@/components/primitives/data-table"
import { StatusPill } from "@/components/primitives/status-pill"

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// The Library table (plans/07 §2.1). Pure presentational — takes `documents`
// as a prop, never fetches. `vehiclePlates` maps vehicle ids to plate numbers.
export function DocumentLibraryTable({
  documents,
  vehiclePlates,
  canDelete,
  onDelete,
}: {
  documents: DocumentResponse[]
  vehiclePlates?: Record<string, string>
  canDelete?: boolean
  onDelete?: (doc: DocumentResponse) => void
}) {
  const columns: DataTableColumn<DocumentResponse>[] = [
    {
      key: "filename",
      header: "Filename",
      cell: (row) => (
        <span className="flex items-center gap-2 font-medium text-foreground">
          <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          {row.filename}
        </span>
      ),
    },
    { key: "type", header: "Type", cell: (row) => DOCUMENT_TYPE_LABELS[row.document_type] },
    { key: "vehicle", header: "Vehicle", cell: (row) => (row.vehicle_id ? (vehiclePlates?.[row.vehicle_id] ?? row.vehicle_id) : "—") },
    { key: "version", header: "Version", align: "right", cell: (row) => `v${row.version}` },
    { key: "size", header: "Size", align: "right", cell: (row) => formatSize(row.size_bytes) },
    {
      key: "status",
      header: "Status",
      cell: (row) => (
        <div>
        <StatusPill tone={DOCUMENT_STATUS_TONE[row.status]}>
          {row.status === "processing" ? (
            <span className="flex items-center gap-1">
              <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-current motion-reduce:animate-none" />
              Processing
            </span>
          ) : (
            row.status[0]!.toUpperCase() + row.status.slice(1)
          )}
        </StatusPill>
          {row.status === "failed" && row.error_message ? (
            <p className="mt-1 max-w-xs text-caption text-destructive">{row.error_message}</p>
          ) : null}
        </div>
      ),
    },
    { key: "updated", header: "Updated", cell: (row) => formatDateTime(row.updated_at) },
  ]

  if (canDelete) {
    columns.push({
      key: "actions",
      header: "",
      align: "right",
      cell: (row) => (
        <Button variant="ghost" size="sm" onClick={() => onDelete?.(row)}>
          Delete
        </Button>
      ),
    })
  }

  return <DataTable columns={columns} rows={documents} getRowId={(row) => row.id} />
}

export { formatSize }
