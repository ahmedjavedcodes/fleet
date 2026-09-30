import { screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { AdminDashboard } from "@/app/(app)/dashboard/_components/admin-dashboard"
import { renderWithProviders as render } from "../../../../test-utils"

const mockUseCurrentUser = vi.fn()
vi.mock("@/lib/auth/use-current-user", () => ({ useCurrentUser: () => mockUseCurrentUser() }))

const mockSummary = vi.fn()
const mockFuelTrends = vi.fn()
const mockCalendar = vi.fn()
const mockFleetHealth = vi.fn()
vi.mock("@/lib/api/dashboard", () => ({
  useDashboardSummary: () => mockSummary(),
  useFuelTrends: () => mockFuelTrends(),
  useMaintenanceCalendar: () => mockCalendar(),
  useFleetHealth: () => mockFleetHealth(),
}))

function pendingQuery() {
  return { data: undefined, isPending: true, error: null, refetch: vi.fn() }
}
function successQuery<T>(data: T) {
  return { data, isPending: false, error: null, refetch: vi.fn() }
}
function errorQuery(error: unknown) {
  return { data: undefined, isPending: false, error, refetch: vi.fn() }
}

describe("AdminDashboard", () => {
  beforeEach(() => {
    mockUseCurrentUser.mockReturnValue({ role: "admin" })
    mockFuelTrends.mockReturnValue(pendingQuery())
    mockCalendar.mockReturnValue(pendingQuery())
    mockFleetHealth.mockReturnValue(pendingQuery())
  })

  it("formats every KPI value, including money from a decimal string, and shows a real zero rather than hiding it", () => {
    mockSummary.mockReturnValue(
      successQuery({
        total_vehicles: 24,
        active_drivers: 9,
        month_fuel_cost: "125000.0000",
        overdue_maintenance_count: 3,
        low_stock_parts_count: 1,
        open_incidents_count: 0,
      })
    )
    render(<AdminDashboard />)

    expect(screen.getByText("24")).toBeInTheDocument()
    expect(screen.getByText("9")).toBeInTheDocument()
    expect(screen.getByText("3")).toBeInTheDocument()
    expect(screen.getByText(/125,000/)).toBeInTheDocument()
    // open_incidents_count: 0 is a real value, not an empty/hidden tile.
    expect(screen.getByText("0")).toBeInTheDocument()
  })

  it("renders null fleet-health signals as n/a, never 0", () => {
    mockSummary.mockReturnValue(pendingQuery())
    mockFleetHealth.mockReturnValue(
      successQuery([
        {
          vehicle_id: "v1",
          plate_number: "AB-1234",
          health_score: 80,
          signals: { compliance: null, incidents: 90, maintenance_currency: null, fuel_efficiency: 70 },
          current_cost_per_km: "30.9000",
          previous_cost_per_km: "32.1000",
        },
      ])
    )
    render(<AdminDashboard />)
    expect(screen.getAllByText("n/a")).toHaveLength(2)
    expect(screen.getByText("90")).toBeInTheDocument()
    expect(screen.getByText("70")).toBeInTheDocument()
  })

  it("renders AccessDenied for just the fleet-health region on a 403, leaving the rest of the page intact", () => {
    mockSummary.mockReturnValue(
      successQuery({
        total_vehicles: 24,
        active_drivers: 9,
        month_fuel_cost: "0",
        overdue_maintenance_count: 0,
        low_stock_parts_count: 0,
        open_incidents_count: 0,
      })
    )
    mockFleetHealth.mockReturnValue(errorQuery({ kind: "forbidden", status: 403, message: "Not enough permissions" }))
    render(<AdminDashboard />)

    expect(screen.getByText("You don't have access to fleet health")).toBeInTheDocument()
    // The KPI region rendered independently — a 403 in one region doesn't
    // blank the page (plans/04 §2: independent QueryRegions).
    expect(screen.getByText("24")).toBeInTheDocument()
  })

  it("sorts the maintenance calendar overdue-first", () => {
    mockSummary.mockReturnValue(pendingQuery())
    mockCalendar.mockReturnValue(
      successQuery([
        { vehicle_id: "v1", plate_number: "UP-1", service_type: "oil_change", due_date: "2026-08-01", due_km: null, status: "upcoming" },
        { vehicle_id: "v2", plate_number: "OD-1", service_type: "brake_service", due_date: null, due_km: 20000, status: "overdue" },
      ])
    )
    render(<AdminDashboard />)
    const rows = screen.getAllByText(/UP-1|OD-1/)
    expect(rows[0]).toHaveTextContent("OD-1")
    expect(rows[1]).toHaveTextContent("UP-1")
  })
})
