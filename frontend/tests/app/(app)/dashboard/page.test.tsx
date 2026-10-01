import { screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import DashboardPage from "@/app/(app)/dashboard/page"
import { renderWithProviders as render } from "../../../test-utils"

const mockUseCurrentUser = vi.fn()
vi.mock("@/lib/auth/use-current-user", () => ({ useCurrentUser: () => mockUseCurrentUser() }))

const pending = () => ({ data: undefined, isPending: true, error: null, refetch: vi.fn() })

// Spies, not throwing mocks — admin/FM are allowed to call these; the test
// asserts on whether they were CALLED, per role, rather than crashing
// mechanic/driver outright (which would also stop the admin/FM cases in
// the same file from exercising the real component).
const useDashboardSummary = vi.fn(pending)
const useFuelTrends = vi.fn(pending)
const useMaintenanceCalendar = vi.fn(pending)
const useFleetHealth = vi.fn(pending)
vi.mock("@/lib/api/dashboard", () => ({
  useDashboardSummary: () => useDashboardSummary(),
  useFuelTrends: () => useFuelTrends(),
  useMaintenanceCalendarPages: () => useMaintenanceCalendar(),
  useFleetHealthPages: () => useFleetHealth(),
}))

vi.mock("@/lib/api/maintenance", () => ({ useMaintenanceLogs: () => pending() }))
vi.mock("@/lib/api/inventory", () => ({ useLowStockParts: () => pending() }))
vi.mock("@/lib/api/compliance", () => ({ useFleetComplianceMatrix: () => pending() }))
vi.mock("@/lib/api/vehicles", () => ({ useVehicles: () => pending(), useVehicle: () => pending() }))
vi.mock("@/lib/api/drivers", () => ({ useDriverAssignments: () => pending(), useDriverTimeline: () => pending() }))
vi.mock("@/lib/api/fuel", () => ({ useFuelLogs: () => pending() }))
vi.mock("@/lib/api/trips", () => ({ useTrips: () => pending() }))
vi.mock("@/lib/api/incidents", () => ({ useIncidents: () => pending() }))

describe("DashboardPage variant selection", () => {
  beforeEach(() => {
    useDashboardSummary.mockClear()
    useFuelTrends.mockClear()
    useMaintenanceCalendar.mockClear()
    useFleetHealth.mockClear()
  })

  it("shows a skeleton while the role is still loading", () => {
    mockUseCurrentUser.mockReturnValue({ role: null, isPending: true })
    const { container } = render(<DashboardPage />)
    expect(container.querySelector('[data-slot="skeleton"]')).toBeTruthy()
  })

  it("renders AdminDashboard for admin, calling the /dashboard/* hooks", () => {
    mockUseCurrentUser.mockReturnValue({ role: "admin", isPending: false, driverProfile: null, user: null, organization: null })
    render(<DashboardPage />)
    expect(useDashboardSummary).toHaveBeenCalled()
    expect(useFleetHealth).toHaveBeenCalled()
  })

  it("renders AdminDashboard for fleet_manager, calling the /dashboard/* hooks", () => {
    mockUseCurrentUser.mockReturnValue({
      role: "fleet_manager",
      isPending: false,
      driverProfile: null,
      user: null,
      organization: null,
    })
    render(<DashboardPage />)
    expect(useDashboardSummary).toHaveBeenCalled()
  })

  it("renders MechanicDashboard for mechanic, never calling a /dashboard/* hook", () => {
    mockUseCurrentUser.mockReturnValue({ role: "mechanic", isPending: false, driverProfile: null, user: null, organization: null })
    render(<DashboardPage />)
    expect(screen.getByText("Recent work")).toBeInTheDocument()
    expect(useDashboardSummary).not.toHaveBeenCalled()
    expect(useFuelTrends).not.toHaveBeenCalled()
    expect(useMaintenanceCalendar).not.toHaveBeenCalled()
    expect(useFleetHealth).not.toHaveBeenCalled()
  })

  it("renders DriverDashboard for driver, never calling a /dashboard/* hook", () => {
    mockUseCurrentUser.mockReturnValue({
      role: "driver",
      isPending: false,
      driverProfile: { id: "driver-1" },
      user: null,
      organization: null,
    })
    render(<DashboardPage />)
    expect(useDashboardSummary).not.toHaveBeenCalled()
    expect(useFuelTrends).not.toHaveBeenCalled()
    expect(useMaintenanceCalendar).not.toHaveBeenCalled()
    expect(useFleetHealth).not.toHaveBeenCalled()
  })
})
