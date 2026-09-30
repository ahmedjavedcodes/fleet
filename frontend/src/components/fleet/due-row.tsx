import type { LucideIcon } from "lucide-react"
import Link from "next/link"
import { cn } from "@/lib/utils"
import { StatusPill } from "@/components/primitives/status-pill"

// Bordered row: icon, name, right-aligned due text + status (plans/00 §5,
// plans/04 §2). Used for both the dashboard's maintenance calendar and the
// vehicle detail page's scheduled-service list (plans/05 §2.4).
export function DueRow({
  icon: Icon,
  title,
  subtitle,
  dueText,
  status,
  href,
  className,
}: {
  icon: LucideIcon
  title: string
  subtitle?: string
  dueText: string
  status: "upcoming" | "overdue"
  href?: string
  className?: string
}) {
  const content = (
    <div
      className={cn(
        "flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5",
        href && "transition duration-150 ease-standard hover:bg-muted",
        className
      )}
    >
      {/* The title takes the remaining width and wraps rather than truncating;
          the due text + pill on the right never shrink, so they stay aligned. */}
      <div className="flex min-w-0 flex-1 items-center gap-2.5">
        <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium wrap-break-word text-foreground">{title}</p>
          {subtitle ? <p className="text-caption wrap-break-word text-muted-foreground">{subtitle}</p> : null}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <span className="text-caption whitespace-nowrap text-muted-foreground">{dueText}</span>
        <StatusPill tone={status === "overdue" ? "destructive" : "warning"}>
          {status === "overdue" ? "Overdue" : "Upcoming"}
        </StatusPill>
      </div>
    </div>
  )

  if (!href) return content

  return (
    <Link href={href} className="block rounded-lg focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
      {content}
    </Link>
  )
}
