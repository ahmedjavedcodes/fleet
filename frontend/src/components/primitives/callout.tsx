import { TriangleAlert, type LucideIcon } from "lucide-react"
import Link from "next/link"
import { ChevronRight } from "lucide-react"
import { cn } from "@/lib/utils"

// A warning-toned banner with a title, detail and an optional link to the
// underlying record (plans/00 §5) — the fuel-anomaly / open-incident
// callout on the vehicle detail page's trip panel (plans/05 §2.5).
export function Callout({
  icon: Icon = TriangleAlert,
  title,
  detail,
  href,
  className,
}: {
  icon?: LucideIcon
  title: string
  detail: string
  href?: string
  className?: string
}) {
  const content = (
    <div className={cn("flex items-start gap-3 rounded-lg border border-warning-border bg-warning-soft p-3", className)}>
      <Icon className="mt-0.5 size-4 shrink-0 text-warning-icon" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <p className="text-caption text-muted-foreground">{detail}</p>
      </div>
      {href ? <ChevronRight className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden /> : null}
    </div>
  )

  if (!href) return content
  return (
    <Link href={href} className="block rounded-lg focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
      {content}
    </Link>
  )
}
