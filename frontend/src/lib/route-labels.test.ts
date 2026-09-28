import { describe, expect, it } from "vitest"
import { routeLabel } from "./route-labels"

describe("routeLabel", () => {
  it("matches CLAUDE.md §3's sidebar labels", () => {
    expect(routeLabel("/dashboard")).toBe("Overview")
    expect(routeLabel("/foundation/vehicles")).toBe("Vehicles")
    expect(routeLabel("/foundation/vehicles/abc-123")).toBe("Vehicles")
    expect(routeLabel("/fuel")).toBe("Fuel & Trips")
  })

  it("falls back to the app name for an unmatched path", () => {
    expect(routeLabel("/some-future-page")).toBe("FleetOps")
  })
})
