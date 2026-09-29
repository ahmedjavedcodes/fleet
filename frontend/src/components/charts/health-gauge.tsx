import { healthScoreLabel } from "@/lib/health-score"
import { cn } from "@/lib/utils"

const SIZES = {
  sm: { box: 72, stroke: 8, font: "text-base" },
  lg: { box: 160, stroke: 14, font: "text-h1" },
} as const

const CENTER = 100
const RADIUS = 90

/** A point on the gauge's semicircle for a fraction `f` (0–1) of it filled,
 * sweeping left (f=0) → top (f=0.5) → right (f=1). */
function pointAt(f: number): { x: number; y: number } {
  const angleDeg = 180 - f * 180
  const angleRad = (angleDeg * Math.PI) / 180
  return { x: CENTER + RADIUS * Math.cos(angleRad), y: CENTER - RADIUS * Math.sin(angleRad) }
}

function arcPath(fFrom: number, fTo: number): string {
  const start = pointAt(fFrom)
  const end = pointAt(fTo)
  const largeArc = fTo - fFrom > 0.5 ? 1 : 0
  return `M ${start.x} ${start.y} A ${RADIUS} ${RADIUS} 0 ${largeArc} 1 ${end.x} ${end.y}`
}

// Semicircle arc with a gradient value stroke on a track (plans/00 §5,
// plans/04 §5). `score: null` renders an empty track and "n/a" — CLAUDE.md
// §4.4: a null signal is "n/a", never 0.
export function HealthGauge({
  score,
  size = "lg",
  className,
}: {
  score: number | null
  size?: keyof typeof SIZES
  className?: string
}) {
  const { box, stroke, font } = SIZES[size]
  const fraction = score === null ? 0 : Math.max(0, Math.min(100, score)) / 100
  const { label } = score === null ? { label: null } : healthScoreLabel(score)
  const gradientId = `health-gauge-gradient-${size}`

  return (
    <div
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={score ?? undefined}
      aria-valuetext={score === null ? "Not available" : `${score} out of 100 — ${label}`}
      className={cn("relative inline-flex flex-col items-center", className)}
      style={{ width: box }}
    >
      <svg viewBox="0 0 200 110" width={box} height={box / 2 + 10} aria-hidden>
        <defs>
          <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="var(--gauge-start)" />
            <stop offset="100%" stopColor="var(--gauge-end)" />
          </linearGradient>
        </defs>
        <path d={arcPath(0, 1)} fill="none" stroke="var(--gauge-track)" strokeWidth={stroke} strokeLinecap="round" />
        {score !== null && fraction > 0 && (
          <path
            d={arcPath(0, fraction)}
            fill="none"
            stroke={`url(#${gradientId})`}
            strokeWidth={stroke}
            strokeLinecap="round"
          />
        )}
      </svg>
      <div className="absolute inset-x-0 bottom-0 flex flex-col items-center leading-none">
        {score === null ? (
          <span className="text-caption text-muted-foreground">n/a</span>
        ) : (
          <span className={cn(font, "font-semibold text-foreground")}>
            {score}
            <span className="text-caption font-normal text-muted-foreground">/100</span>
          </span>
        )}
      </div>
    </div>
  )
}
