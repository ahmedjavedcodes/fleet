import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"

export type StatusPillTone =
  | "success"
  | "warning"
  | "info"
  | "neutral"
  | "destructive"
  | "sev-minor"
  | "sev-moderate"
  | "sev-severe"
  | "sev-critical"

const DOT_CLASSES: Record<StatusPillTone, string> = {
  success: "bg-success",
  warning: "bg-warning",
  info: "bg-info",
  neutral: "bg-muted-foreground",
  destructive: "bg-destructive",
  "sev-minor": "bg-info",
  "sev-moderate": "bg-warning",
  "sev-severe": "bg-primary",
  "sev-critical": "bg-destructive",
}

// A soft-bg pill with a colored dot and a text label (the "On Route" pill in
// the reference — plans/00 §5). Color is never the only signal: the label
// text is required, never an icon- or color-only variant (CLAUDE.md §1.3).
export function StatusPill({
  tone,
  children,
  className,
}: {
  tone: StatusPillTone
  children: React.ReactNode
  className?: string
}) {
  return (
    <Badge variant={tone} className={cn("gap-1.5", className)}>
      <span className={cn("size-1.5 rounded-full", DOT_CLASSES[tone])} aria-hidden />
      {children}
    </Badge>
  )
}
