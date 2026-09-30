import type { StatusPillTone } from "@/components/primitives/status-pill"

// Fleet-health score → label/tone. The backend returns only a 0–100 int
// (dashboard.ts's health_score); it has no opinion on "Good/Fair/Poor" —
// that's a UI-only presentation layer. The label, the badge tone and the
// gauge's stroke colour all come from this one function so they can't disagree
// (dashboard fleet-health table, vehicle health panel, insights).
export type HealthLabel = "Good" | "Fair" | "Poor"

export const HEALTH_GOOD_MIN = 80
export const HEALTH_FAIR_MIN = 50

/** Score clamped to the 0–100 range the gauge and labels are defined on. */
export function clampScore(score: number): number {
  return Math.max(0, Math.min(100, score))
}

export function healthScoreLabel(score: number): { label: HealthLabel; tone: StatusPillTone } {
  const s = clampScore(score)
  if (s >= HEALTH_GOOD_MIN) return { label: "Good", tone: "success" }
  if (s >= HEALTH_FAIR_MIN) return { label: "Fair", tone: "warning" }
  return { label: "Poor", tone: "destructive" }
}
