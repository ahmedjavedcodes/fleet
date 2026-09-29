import { PageHeader } from "@/components/layout/page-header"
import { NotAvailableYet } from "@/components/states/not-available-yet"

// The Document Library, upload flow and citation components exist
// (src/components/ai/) and are unit-tested, but nothing on this page
// imports them — /documents has no backend on this branch (plans/07,
// 2026-09-29 constraint: `backend` is never merged into `frontend`).
export default function DocumentsPage() {
  return (
    <>
      <PageHeader crumbs={[{ label: "Documents" }]} />
      <NotAvailableYet feature="The document library" />
    </>
  )
}
