import { Info } from "lucide-react"
import { cn } from "@/lib/utils"
import { IconTile } from "@/components/primitives/icon-tile"

// For CLAUDE.md §5.5 features only (chat, notifications, insights NL
// search) — a genuinely honest state for a page whose *backend* doesn't
// exist yet, distinct from EmptyState/the "coming soon" placeholder used
// for pages whose backend exists but whose UI hasn't been built (plans/03
// §7; see route-placeholder.tsx).
export function NotAvailableYet({ feature, className }: { feature: string; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center gap-3 rounded-xl border border-border bg-card p-8 text-center", className)}>
      <IconTile icon={Info} tone="info" size="lg" />
      <div>
        <p className="text-h3 font-semibold text-foreground">{feature} isn&apos;t available yet</p>
        <p className="mt-1 text-sm text-muted-foreground">This feature is waiting on its backend API.</p>
      </div>
    </div>
  )
}
