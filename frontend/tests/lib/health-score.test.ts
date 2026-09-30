import { describe, expect, it } from "vitest"
import { clampScore, healthScoreLabel } from "@/lib/health-score"

describe("healthScoreLabel", () => {
  it("labels the boundaries: below 50 Poor, 50-79 Fair, 80 and up Good", () => {
    expect(healthScoreLabel(100)).toEqual({ label: "Good", tone: "success" })
    expect(healthScoreLabel(80)).toEqual({ label: "Good", tone: "success" })
    expect(healthScoreLabel(79)).toEqual({ label: "Fair", tone: "warning" })
    expect(healthScoreLabel(50)).toEqual({ label: "Fair", tone: "warning" })
    expect(healthScoreLabel(49)).toEqual({ label: "Poor", tone: "destructive" })
    expect(healthScoreLabel(0)).toEqual({ label: "Poor", tone: "destructive" })
  })

  it("treats out-of-range scores as the nearest end of the range", () => {
    expect(healthScoreLabel(140).label).toBe("Good")
    expect(healthScoreLabel(-5).label).toBe("Poor")
    expect(clampScore(140)).toBe(100)
    expect(clampScore(-5)).toBe(0)
  })
})
