import type { LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"

// The reference's rounded colored square with a glyph (plans/00 §5) —
// generalized beyond the KPI tile colors so states/* (EmptyState,
// ErrorState, AccessDenied) can reuse it with a muted or
// status tone instead of inventing their own icon-square markup.
export type IconTileTone =
  | "brand"
  | "success"
  | "warning"
  | "info"
  | "destructive"
  | "muted"
  | "green"
  | "blue"
  | "amber"
  | "purple"

const TONE_CLASSES: Record<IconTileTone, string> = {
  brand: "bg-primary-soft text-primary",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning-icon",
  info: "bg-info-soft text-info",
  destructive: "bg-destructive-soft text-destructive",
  muted: "bg-muted text-muted-foreground",
  // KPI tile colors: glyphs are decorative (--tile-foreground, white in both
  // themes), so contrast against the tile color doesn't need checking
  // (CLAUDE.md §1.2).
  green: "bg-tile-green text-tile-foreground",
  blue: "bg-tile-blue text-tile-foreground",
  amber: "bg-tile-amber text-tile-foreground",
  purple: "bg-tile-purple text-tile-foreground",
}

const SIZE_CLASSES = { sm: "size-8 rounded-md", md: "size-9 rounded-md", lg: "size-12 rounded-lg" } as const
const ICON_SIZE_CLASSES = { sm: "size-4", md: "size-5", lg: "size-6" } as const

export function IconTile({
  icon: Icon,
  tone,
  size = "md",
  className,
}: {
  icon: LucideIcon
  tone: IconTileTone
  size?: keyof typeof SIZE_CLASSES
  className?: string
}) {
  return (
    <span
      aria-hidden
      className={cn("inline-flex shrink-0 items-center justify-center", SIZE_CLASSES[size], TONE_CLASSES[tone], className)}
    >
      <Icon className={ICON_SIZE_CLASSES[size]} />
    </span>
  )
}
