import { screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { HealthPanel } from "@/app/(app)/foundation/vehicles/[id]/_components/health-panel"
import type { VehicleHealthScore } from "@/lib/schemas/dashboard"
import { renderWithProviders as render } from "../../../../../test-utils"

const VEHICLE_ID = "11111111-1111-4111-8111-111111111111"

const mockFleetHealth = vi.fn()
vi.mock("@/lib/api/dashboard", () => ({ useFleetHealth: () => mockFleetHealth() }))

function withFuel(fuel_efficiency: number | null, current: string | null, previous: string | null): VehicleHealthScore {
  return {
    vehicle_id: VEHICLE_ID,
    plate_number: "AB-1234",
    health_score: 80,
    signals: { compliance: 90, incidents: 100, maintenance_currency: 60, fuel_efficiency },
    current_cost_per_km: current,
    previous_cost_per_km: previous,
  }
}

function fuelRow() {
  return screen.getByText("Fuel efficiency").closest("a")!
}

describe("HealthPanel fuel efficiency", () => {
  beforeEach(() => mockFleetHealth.mockReset())

  function renderWith(entry: VehicleHealthScore) {
    mockFleetHealth.mockReturnValue({ data: [entry], isPending: false, error: null, refetch: vi.fn() })
    render(<HealthPanel vehicleId={VEHICLE_ID} />)
  }

  it("shows the trend score when both periods exist", () => {
    renderWith(withFuel(100, "29.0000", "31.0000"))
    expect(fuelRow()).toHaveTextContent("Cost per km vs the previous period")
    expect(fuelRow()).toHaveTextContent("100")
  })

  it("shows the current cost per km, with no trend score, when there is no previous period", () => {
    renderWith(withFuel(null, "30.9000", null))
    expect(fuelRow()).toHaveTextContent(/30\.90\/km/)
    expect(fuelRow()).toHaveTextContent("no earlier period to compare")
    expect(fuelRow()).not.toHaveTextContent("n/a")
  })

  it("says there isn't enough history, never 'n/a', when there are no readings", () => {
    renderWith(withFuel(null, null, null))
    expect(fuelRow()).toHaveTextContent("Insufficient historical data")
    expect(fuelRow()).not.toHaveTextContent("n/a")
  })
})
