import { screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import VehicleDetailPage from "@/app/(app)/foundation/vehicles/[id]/page"
import { renderWithProviders as render } from "../../../../../test-utils"

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "v1" }) }))

const mockUseCurrentUser = vi.fn()
vi.mock("@/lib/auth/use-current-user", () => ({ useCurrentUser: () => mockUseCurrentUser() }))

const pending = () => ({ data: undefined, isPending: true, error: null, refetch: vi.fn() })
const success = <T,>(data: T) => ({ data, isPending: false, error: null, refetch: vi.fn() })

const mockVehicle = vi.fn(pending)
const mockAssignments = vi.fn(pending)
vi.mock("@/lib/api/vehicles", () => ({
  useVehicle: () => mockVehicle(),
  useVehicleAssignments: () => mockAssignments(),
  useVehicleCompliance: () => pending(),
  useAssignVehicle: () => ({ mutate: vi.fn(), isPending: false }),
  useReleaseVehicle: () => ({ mutate: vi.fn(), isPending: false }),
}))

const mockDriver = vi.fn(pending)
vi.mock("@/lib/api/drivers", () => ({ useDriver: () => mockDriver(), useDrivers: () => pending() }))

const useFleetHealth = vi.fn(pending)
vi.mock("@/lib/api/dashboard", () => ({ useFleetHealth: () => useFleetHealth() }))
vi.mock("@/lib/api/fuel", () => ({ useFuelSummary: () => pending(), useFuelLogs: () => pending() }))
const useTrips = vi.fn(pending)
vi.mock("@/lib/api/trips", () => ({ useTrips: () => useTrips() }))
vi.mock("@/lib/api/maintenance", () => ({ useMaintenanceLogs: () => pending() }))
vi.mock("@/lib/api/incidents", () => ({ useIncidents: () => pending() }))

const VEHICLE = {
  id: "v1",
  organization_id: "org1",
  plate_number: "LEA-1001",
  make: "Toyota",
  model: "Hilux",
  year: 2022,
  vin: "VIN1",
  fuel_type: "diesel" as const,
  status: "active" as const,
  current_odometer: 40000,
  service_interval_km: null,
  service_interval_months: null,
}

describe("VehicleDetailPage", () => {
  beforeEach(() => {
    mockVehicle.mockReturnValue(success(VEHICLE))
    mockAssignments.mockReturnValue(success([]))
    useFleetHealth.mockClear()
    useTrips.mockClear()
  })

  it("shows a not-found error state when the vehicle 404s", () => {
    mockUseCurrentUser.mockReturnValue({ role: "admin" })
    mockVehicle.mockReturnValue({ data: undefined, isPending: false, error: { kind: "not_found", status: 404, message: "This vehicle doesn't exist." }, refetch: vi.fn() })
    render(<VehicleDetailPage />)
    expect(screen.getByText("This vehicle doesn't exist.")).toBeInTheDocument()
  })

  it("mechanic never renders the health panel (dashboard:read excludes M)", () => {
    mockUseCurrentUser.mockReturnValue({ role: "mechanic" })
    render(<VehicleDetailPage />)
    expect(useFleetHealth).not.toHaveBeenCalled()
    expect(screen.queryByText("Vehicle Health Score")).not.toBeInTheDocument()
    expect(screen.queryByText("Trip performance")).not.toBeInTheDocument()
  })

  it("admin renders the health panel and trip panel", () => {
    mockUseCurrentUser.mockReturnValue({ role: "admin" })
    render(<VehicleDetailPage />)
    expect(screen.getByText("Vehicle Health Score")).toBeInTheDocument()
    expect(screen.getByText("Trip performance")).toBeInTheDocument()
  })

  it("driver sees a driver-scoped trip panel title, not the admin one", () => {
    mockUseCurrentUser.mockReturnValue({ role: "driver" })
    render(<VehicleDetailPage />)
    expect(screen.getByText("Your trips on this vehicle")).toBeInTheDocument()
    expect(screen.queryByText("Vehicle Health Score")).not.toBeInTheDocument()
  })

  it("renders the plate number and vehicle meta once loaded", () => {
    mockUseCurrentUser.mockReturnValue({ role: "admin" })
    render(<VehicleDetailPage />)
    expect(screen.getByText("LEA-1001")).toBeInTheDocument()
    expect(screen.getByText(/Toyota Hilux/)).toBeInTheDocument()
  })
})
