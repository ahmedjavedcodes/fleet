import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
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
  useMaintenanceCalendarPages: () => mockCalendar(),
  useFleetHealthPages: () => mockFleetHealth(),
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
// A load-more list: what the paged hooks return (the items fetched so far, the total, and the next-page controls).
function pagedQuery<T>(items: T[], total: number | null = items.length, hasNextPage = false) {
  const fetchNextPage = vi.fn()
  return { ...successQuery({ items, total }), hasNextPage, isFetchingNextPage: false, fetchNextPage }
}

const SUMMARY = {
  total_vehicles: 24,
  active_drivers: 9,
  month_fuel_cost: "125000.0000",
  overdue_maintenance_count: 3,
  low_stock_parts_count: 1,
  open_incidents_count: 0,
  active_suppliers_count: 7,
}

function healthRow(n: number) {
  return {
    vehicle_id: `v${n}`,
    plate_number: `HLT-${String(n).padStart(3, "0")}`,
    health_score: 40 + n,
    signals: { compliance: 50, incidents: 60, maintenance_currency: 70, fuel_efficiency: 80 },
    current_cost_per_km: null,
    previous_cost_per_km: null,
  }
}

describe("AdminDashboard", () => {
  beforeEach(() => {
    mockUseCurrentUser.mockReturnValue({ role: "admin" })
    mockFuelTrends.mockReturnValue(pendingQuery())
    mockCalendar.mockReturnValue(pendingQuery())
    mockFleetHealth.mockReturnValue(pendingQuery())
  })

  it("formats every KPI value, including money from a decimal string, and shows a real zero rather than hiding it", () => {
    mockSummary.mockReturnValue(successQuery({ ...SUMMARY, active_suppliers_count: 12 }))
    render(<AdminDashboard />)

    expect(screen.getByText("24")).toBeInTheDocument()
    expect(screen.getByText("9")).toBeInTheDocument()
    expect(screen.getByText("3")).toBeInTheDocument()
    expect(screen.getByText("12")).toBeInTheDocument()
    expect(screen.getByText(/125,000/)).toBeInTheDocument()
    // open_incidents_count: 0 is a real value, not an empty/hidden tile.
    expect(screen.getByText("0")).toBeInTheDocument()
  })

  it("shows an Active suppliers tile in place of the Low-stock parts one", () => {
    mockSummary.mockReturnValue(successQuery(SUMMARY))
    render(<AdminDashboard />)

    expect(screen.getByText("Active suppliers")).toBeInTheDocument()
    expect(screen.getByText("7")).toBeInTheDocument()
    expect(screen.getByText("Active suppliers").closest("a")).toHaveAttribute("href", "/foundation/suppliers")
    expect(screen.queryByText("Low-stock parts")).not.toBeInTheDocument()
    expect(screen.queryByText(/low-stock/i)).not.toBeInTheDocument()
  })

  it("renders null fleet-health signals as n/a, never 0", () => {
    mockSummary.mockReturnValue(pendingQuery())
    mockFleetHealth.mockReturnValue(
      pagedQuery([
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
    mockSummary.mockReturnValue(successQuery({ ...SUMMARY, month_fuel_cost: "0", overdue_maintenance_count: 0 }))
    mockFleetHealth.mockReturnValue(errorQuery({ kind: "forbidden", status: 403, message: "Not enough permissions" }))
    render(<AdminDashboard />)

    expect(screen.getByText("You don't have access to fleet health")).toBeInTheDocument()
    // The KPI region rendered independently — a 403 in one region doesn't
    // blank the page (plans/04 §2: independent QueryRegions).
    expect(screen.getByText("24")).toBeInTheDocument()
  })

  it("lists the maintenance calendar in the order the backend sent it (overdue first), without re-sorting", () => {
    mockSummary.mockReturnValue(pendingQuery())
    mockCalendar.mockReturnValue(
      pagedQuery([
        { vehicle_id: "v2", plate_number: "OD-1", service_type: "brake_service", due_date: null, due_km: 20000, status: "overdue" },
        { vehicle_id: "v1", plate_number: "UP-1", service_type: "oil_change", due_date: "2026-08-01", due_km: null, status: "upcoming" },
      ])
    )
    render(<AdminDashboard />)
    const rows = screen.getAllByText(/UP-1|OD-1/)
    expect(rows[0]).toHaveTextContent("OD-1")
    expect(rows[1]).toHaveTextContent("UP-1")
  })

  describe("loading lists a page at a time", () => {
    it("shows how many of the total are loaded and fetches the next page on request, for the calendar", async () => {
      mockSummary.mockReturnValue(pendingQuery())
      const calendar = pagedQuery(
        [
          { vehicle_id: "v1", plate_number: "OD-1", service_type: "oil_change", due_date: "2026-08-01", due_km: null, status: "overdue" },
          { vehicle_id: "v2", plate_number: "OD-2", service_type: "oil_change", due_date: "2026-08-02", due_km: null, status: "overdue" },
        ],
        2094,
        true
      )
      mockCalendar.mockReturnValue(calendar)
      render(<AdminDashboard />)

      expect(screen.getByText("Showing 2 of 2,094 items")).toBeInTheDocument()
      await userEvent.setup().click(screen.getByRole("button", { name: "Load more" }))
      expect(calendar.fetchNextPage).toHaveBeenCalledTimes(1)
    })

    it("does the same for fleet health, and renders only the rows it has been given", async () => {
      mockSummary.mockReturnValue(pendingQuery())
      const health = pagedQuery(Array.from({ length: 25 }, (_, i) => healthRow(i + 1)), 486, true)
      mockFleetHealth.mockReturnValue(health)
      render(<AdminDashboard />)

      expect(screen.getByText("Showing 25 of 486 vehicles")).toBeInTheDocument()
      expect(screen.getAllByRole("link", { name: /^HLT-/ })).toHaveLength(25) // 25 rows in the DOM, not 486
      await userEvent.setup().click(screen.getByRole("button", { name: "Load more" }))
      expect(health.fetchNextPage).toHaveBeenCalledTimes(1)
    })

    it("offers no Load more once everything is loaded", () => {
      mockSummary.mockReturnValue(pendingQuery())
      mockFleetHealth.mockReturnValue(pagedQuery([healthRow(1), healthRow(2)], 2, false))
      mockCalendar.mockReturnValue(pagedQuery([], 0, false))
      render(<AdminDashboard />)

      expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument()
      expect(screen.queryByText(/Showing/)).not.toBeInTheDocument()
    })

    it("disables the button while the next page is loading", () => {
      mockSummary.mockReturnValue(pendingQuery())
      mockFleetHealth.mockReturnValue({ ...pagedQuery([healthRow(1)], 40, true), isFetchingNextPage: true })
      render(<AdminDashboard />)

      expect(screen.getByRole("button", { name: "Loading…" })).toBeDisabled()
    })
  })
})
