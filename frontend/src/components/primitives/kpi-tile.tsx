import type { LucideIcon } from "lucide-react"
import Link from "next/link"
import { formatInt, formatMoney, formatNumber } from "@/lib/api/decimal"
import { cn } from "@/lib/utils"
import { CardContent } from "@/components/ui/card"
import { IconTile } from "./icon-tile"
import { InnerCard } from "./inner-card"

export type KpiTileFormat = "money" | "number" | "count"

function formatKpiValue(value: string, format: KpiTileFormat): string {
  switch (format) {
    case "money":
      return formatMoney(value)
    case "number":
      return formatNumber(value)
    case "count":
      return formatInt(Number(value))
  }
}

// Colored icon square + label + big number + small unit (plans/00 §5).
// `value` is the raw backend value — a decimal string for money/number, or
// a plain count as a string — and `format` picks the lib/api/decimal
// helper; components never format money by hand (CLAUDE.md §1.3).
export function KpiTile({
  icon,
  tone,
  label,
  value,
  format,
  unit,
  href,
  className,
}: {
  icon: LucideIcon
  tone: "green" | "blue" | "amber" | "purple"
  label: string
  value: string
  format: KpiTileFormat
  unit?: string
  href?: string
  className?: string
}) {
  const body = (
    <InnerCard className={className}>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-2">
          <IconTile icon={icon} tone={tone} />
          <span className="text-caption text-muted-foreground">{label}</span>
        </div>
        <p className="text-h1 text-foreground">
          {formatKpiValue(value, format)}
          {unit ? <span className="ml-1.5 text-caption font-normal text-muted-foreground">{unit}</span> : null}
        </p>
      </CardContent>
    </InnerCard>
  )

  if (!href) return body

  return (
    <Link
      href={href}
      className={cn(
        "block rounded-xl transition duration-150 ease-standard hover:shadow-card-hover",
        "focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      )}
    >
      {body}
    </Link>
  )
}
