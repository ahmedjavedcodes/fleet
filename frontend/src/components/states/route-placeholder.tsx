import { Construction } from "lucide-react"
import type { Crumb } from "@/components/primitives/breadcrumbs"
import { PageHeader } from "@/components/layout/page-header"
import { EmptyState } from "./empty-state"

// For a route whose *backend* already exists but whose UI hasn't been
// built yet (dashboard, foundation/*, fuel, maintenance, …) — an honest
// "coming soon" state, distinct from NotAvailableYet (reserved for the
// CLAUDE.md §5.5 features whose backend genuinely doesn't exist). Every
// scaffolded route's page.tsx renders this until its own plan lands
// (plans/03 §7).
export function RoutePlaceholder({ title, crumbs }: { title: string; crumbs: Crumb[] }) {
  return (
    <>
      <PageHeader crumbs={crumbs} />
      <EmptyState
        icon={Construction}
        title={`${title} is being built`}
        description="This page's backend already exists — the UI for it is coming in a later phase."
      />
    </>
  )
}
