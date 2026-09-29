import type { StatusPillTone } from "@/components/primitives/status-pill"

// Fleet-health score → label/tone. The backend returns only a 0–100 int
// (dashboard.ts's health_score); it has no opinion on "Good/Fair/Poor" —
// that's a UI-only presentation layer, documented here since both the
// dashboard's fleet-health table and the vehicle detail page's health panel
// use it (plans/04 §2, plans/05 §2.6).
export type HealthLabel = "Good" | "Fair" | "Poor"

export function healthScoreLabel(score: number): { label: HealthLabel; tone: StatusPillTone } {
  if (score >= 75) return { label: "Good", tone: "success" }
  if (score >= 50) return { label: "Fair", tone: "warning" }
  return { label: "Poor", tone: "destructive" }
}
