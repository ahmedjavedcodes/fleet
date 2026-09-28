"use client"

import { useState } from "react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

export type DataTableColumn<T> = {
  key: string
  header: string
  align?: "left" | "right"
  cell: (row: T) => React.ReactNode
  headerClassName?: string
  cellClassName?: string
}

// A typed wrapper over ui/table.tsx (which already carries the sticky
// header, muted-foreground header text and tabular-nums styling —
// CLAUDE.md §1.3) that adds client pagination beyond 50 rows, since the
// backend doesn't paginate most lists (plans/03 §6). Sorting is deferred
// until a page actually needs user-triggered sort (plans/03 §6: "when
// needed") — no consumer requires it yet.
export function DataTable<T>({
  columns,
  rows,
  getRowId,
  pageSize = 50,
  onRowClick,
  caption,
}: {
  columns: DataTableColumn<T>[]
  rows: T[]
  getRowId: (row: T) => string
  pageSize?: number
  onRowClick?: (row: T) => void
  caption?: string
}) {
  const [page, setPage] = useState(0)
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize))
  const currentPage = Math.min(page, pageCount - 1)
  const pageRows = rows.slice(currentPage * pageSize, currentPage * pageSize + pageSize)

  return (
    <div className="space-y-3">
      <Table>
        {caption ? <TableCaption>{caption}</TableCaption> : null}
        <TableHeader>
          <TableRow>
            {columns.map((column) => (
              <TableHead
                key={column.key}
                className={cn(column.align === "right" && "text-right", column.headerClassName)}
              >
                {column.header}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {pageRows.map((row) => (
            <TableRow
              key={getRowId(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={onRowClick ? "cursor-pointer" : undefined}
            >
              {columns.map((column) => (
                <TableCell
                  key={column.key}
                  className={cn(column.align === "right" && "text-right tabular-nums", column.cellClassName)}
                >
                  {column.cell(row)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {pageCount > 1 && (
        <div className="flex items-center justify-between text-caption text-muted-foreground">
          <span>
            Page {currentPage + 1} of {pageCount}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={currentPage === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={currentPage >= pageCount - 1}
              onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
