import { Lock } from "lucide-react"
import Link from "next/link"
import { roleLabel } from "@/lib/auth/role-labels"
import type { UserRole } from "@/lib/schemas/enums"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { IconTile } from "@/components/primitives/icon-tile"

function formatRoleList(roles: readonly UserRole[]): string {
  const labels = roles.map(roleLabel)
  if (labels.length === 1) return labels[0]!
  if (labels.length === 2) return `${labels[0]} and ${labels[1]}`
  return `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`
}

// A page-level 403, or a route the current role can't open (plans/03 §5).
// Never retried — a 403 is a permissions fact, not a transient failure
// (CLAUDE.md §5.3).
export function AccessDenied({
  area,
  allowedRoles,
  className,
}: {
  area: string
  allowedRoles?: readonly UserRole[] | null
  className?: string
}) {
  return (
    <div
      role="alert"
      className={cn("flex flex-col items-center gap-3 rounded-xl border border-border bg-card p-8 text-center", className)}
    >
      <IconTile icon={Lock} tone="muted" size="lg" />
      <div>
        <p className="text-h3 font-semibold text-foreground">You don&apos;t have access to {area}</p>
        {allowedRoles && allowedRoles.length > 0 ? (
          <p className="mt-1 text-sm text-muted-foreground">Available to {formatRoleList(allowedRoles)}.</p>
        ) : null}
      </div>
      <Button asChild variant="outline">
        <Link href="/dashboard">Back to dashboard</Link>
      </Button>
    </div>
  )
}
