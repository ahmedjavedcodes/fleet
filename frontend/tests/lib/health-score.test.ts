import { describe, expect, it } from "vitest"
import { healthScoreLabel } from "@/lib/health-score"

describe("healthScoreLabel", () => {
  it("labels the boundaries correctly", () => {
    expect(healthScoreLabel(100)).toEqual({ label: "Good", tone: "success" })
    expect(healthScoreLabel(75)).toEqual({ label: "Good", tone: "success" })
    expect(healthScoreLabel(74)).toEqual({ label: "Fair", tone: "warning" })
    expect(healthScoreLabel(50)).toEqual({ label: "Fair", tone: "warning" })
    expect(healthScoreLabel(49)).toEqual({ label: "Poor", tone: "destructive" })
    expect(healthScoreLabel(0)).toEqual({ label: "Poor", tone: "destructive" })
  })
})
