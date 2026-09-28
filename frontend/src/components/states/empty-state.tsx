import type { LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { IconTile } from "@/components/primitives/icon-tile"

// icon, title, one-line explanation, optional primary action (plans/03 §5).
// The caller decides whether `action` renders at all — EmptyState doesn't
// know about roles, so a page passes `action` only when `can()` allows it.
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon: LucideIcon
  title: string
  description: string
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-3 rounded-xl border border-dashed border-border bg-card p-8 text-center",
        className
      )}
    >
      <IconTile icon={icon} tone="muted" size="lg" />
      <div>
        <p className="text-h3 font-semibold text-foreground">{title}</p>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  )
}
