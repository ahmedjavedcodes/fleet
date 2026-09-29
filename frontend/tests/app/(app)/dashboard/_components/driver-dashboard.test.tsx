import { screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { DriverDashboard } from "@/app/(app)/dashboard/_components/driver-dashboard"
import { renderWithProviders as render } from "../../../../test-utils"

const mockUseCurrentUser = vi.fn()
vi.mock("@/lib/auth/use-current-user", () => ({ useCurrentUser: () => mockUseCurrentUser() }))

const mockAssignments = vi.fn()
const mockFuelLogs = vi.fn()
const mockTrips = vi.fn()
const mockIncidents = vi.fn()
const mockTimeline = vi.fn()
const mockVehicle = vi.fn()

vi.mock("@/lib/api/drivers", () => ({
  useDriverAssignments: () => mockAssignments(),
  useDriverTimeline: () => mockTimeline(),
}))
vi.mock("@/lib/api/fuel", () => ({ useFuelLogs: () => mockFuelLogs() }))
vi.mock("@/lib/api/trips", () => ({ useTrips: () => mockTrips() }))
vi.mock("@/lib/api/incidents", () => ({ useIncidents: () => mockIncidents() }))
vi.mock("@/lib/api/vehicles", () => ({ useVehicle: () => mockVehicle() }))

function pendingQuery() {
  return { data: undefined, isPending: true, error: null, refetch: vi.fn() }
}
function successQuery<T>(data: T) {
  return { data, isPending: false, error: null, refetch: vi.fn() }
}

describe("DriverDashboard", () => {
  beforeEach(() => {
    mockAssignments.mockReturnValue(pendingQuery())
    mockFuelLogs.mockReturnValue(pendingQuery())
    mockTrips.mockReturnValue(pendingQuery())
    mockIncidents.mockReturnValue(pendingQuery())
    mockTimeline.mockReturnValue(pendingQuery())
    mockVehicle.mockReturnValue(pendingQuery())
  })

  it("shows the no-profile empty state and calls no data hooks when driver_profile is null", () => {
    mockUseCurrentUser.mockReturnValue({ driverProfile: null, isPending: false })
    render(<DriverDashboard />)

    expect(screen.getByText("No driver profile linked")).toBeInTheDocument()
    expect(
      screen.getByText("Your account isn't linked to a driver profile yet. Ask your fleet manager to link it.")
    ).toBeInTheDocument()
    expect(mockAssignments).not.toHaveBeenCalled()
    expect(mockFuelLogs).not.toHaveBeenCalled()
    expect(mockTrips).not.toHaveBeenCalled()
    expect(mockIncidents).not.toHaveBeenCalled()
    expect(mockTimeline).not.toHaveBeenCalled()
  })

  it("shows an anomaly badge on a fuel log where is_anomalous is true, and not otherwise", () => {
    mockUseCurrentUser.mockReturnValue({ driverProfile: { id: "driver-1" }, isPending: false })
    mockFuelLogs.mockReturnValue(
      successQuery([
        {
          id: "f1",
          vehicle_id: "v1",
          driver_id: "driver-1",
          date: "2026-06-01",
          odometer_reading: 1000,
          liters_filled: "10.0000",
          price_per_liter: "280.0000",
          total_cost: "2800.0000",
          cost_per_km: "35.0000",
          is_anomalous: true,
          notes: null,
          created_at: "2026-06-01T00:00:00Z",
        },
        {
          id: "f2",
          vehicle_id: "v1",
          driver_id: "driver-1",
          date: "2026-05-01",
          odometer_reading: 900,
          liters_filled: "10.0000",
          price_per_liter: "280.0000",
          total_cost: "2800.0000",
          cost_per_km: "28.0000",
          is_anomalous: false,
          notes: null,
          created_at: "2026-05-01T00:00:00Z",
        },
      ])
    )
    render(<DriverDashboard />)

    expect(screen.getAllByText("Anomaly")).toHaveLength(1)
  })

  it("shows 'No vehicle assigned' when current_assignment is null", () => {
    mockUseCurrentUser.mockReturnValue({ driverProfile: { id: "driver-1" }, isPending: false })
    mockAssignments.mockReturnValue(successQuery({ driver_id: "driver-1", current_assignment: null, total_vehicles_driven: 0, history: [] }))
    render(<DriverDashboard />)

    expect(screen.getByText("No vehicle assigned")).toBeInTheDocument()
  })
})
