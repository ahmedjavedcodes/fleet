import { clampScore, healthScoreLabel } from "@/lib/health-score"
import { cn } from "@/lib/utils"

const SIZES = {
  sm: { box: 72, stroke: 8, font: "text-base" },
  lg: { box: 160, stroke: 14, font: "text-h1" },
} as const

const STROKE_BY_TONE = {
  success: "var(--success)",
  warning: "var(--warning)",
  destructive: "var(--destructive)",
} as const

// One left-to-right semicircle, used for both the track and the value. Its
// pathLength is normalised to 100, so the value stroke is simply
// `stroke-dasharray: <score> 100` — the score is the arc length, no trigonometry.
const ARC = "M 10 100 A 90 90 0 0 1 190 100"
const PATH_LENGTH = 100

// Semicircle gauge (plans/00 §5, plans/04 §5). The colour follows the same
// thresholds as the Good/Fair/Poor badge (lib/health-score). `score: null`
// renders an empty track and "n/a" — CLAUDE.md §4.4: a null signal is "n/a",
// never 0.
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
  const value = score === null ? 0 : clampScore(score)
  const health = score === null ? null : healthScoreLabel(score)

  return (
    <div
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={score ?? undefined}
      aria-valuetext={health === null ? "Not available" : `${score} out of 100 — ${health.label}`}
      className={cn("relative inline-flex flex-col items-center", className)}
      style={{ width: box }}
    >
      <svg viewBox="0 0 200 110" width={box} height={box / 2 + 10} aria-hidden>
        <path d={ARC} fill="none" stroke="var(--gauge-track)" strokeWidth={stroke} strokeLinecap="round" />
        {health !== null && value > 0 && (
          <path
            data-testid="gauge-value"
            d={ARC}
            pathLength={PATH_LENGTH}
            fill="none"
            stroke={STROKE_BY_TONE[health.tone as keyof typeof STROKE_BY_TONE]}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${value} ${PATH_LENGTH}`}
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
