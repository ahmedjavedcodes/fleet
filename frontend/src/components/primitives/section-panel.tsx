import type { LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"

// The grey outer panel holding white InnerCards ("Maintenance Overview" in
// the reference — plans/00 §5): header icon + title + an optional action
// (a "…" menu, a range select, …), then the panel's content.
export function SectionPanel({
  icon: Icon,
  title,
  action,
  children,
  className,
}: {
  icon?: LucideIcon
  title: string
  action?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section className={cn("rounded-xl bg-panel p-6", className)}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-h2 text-foreground">
          {Icon ? <Icon className="size-5 text-muted-foreground" aria-hidden /> : null}
          {title}
        </h2>
        {action}
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  )
}
