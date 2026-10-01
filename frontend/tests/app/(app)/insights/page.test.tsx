import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import InsightsPage from "@/app/(app)/insights/page"
import { renderWithProviders as render } from "../../../test-utils"

vi.mock("@/lib/auth/use-current-user", () => ({ useCurrentUser: () => ({ role: "admin" }) }))
const mockTrends = vi.fn()
const mockCalendar = vi.fn()
vi.mock("@/lib/api/dashboard", () => ({
  useFuelTrends: (months: number, vehicleId?: string) => mockTrends(months, vehicleId),
  useMaintenanceCalendar: (windowDays: number, options?: unknown) => mockCalendar(windowDays, options),
  useFleetHealth: () => ({ data: [], isPending: false, error: null, refetch: vi.fn() }),
}))
vi.mock("@/lib/api/vehicles", () => ({
  useVehicles: () => ({ data: [{ id: "veh-1", plate_number: "AB-1234", make: "Toyota", model: "Hilux" }, { id: "veh-2", plate_number: "CD-5678", make: "Ford", model: "Transit" }] }),
}))

const done = (data: unknown) => ({ data, isPending: false, error: null, refetch: vi.fn() })

describe("InsightsPage vehicle filter", () => {
  beforeEach(() => {
    mockTrends.mockReturnValue(done([]))
    mockCalendar.mockReturnValue(done([]))
  })

  it("starts on the whole fleet, with the calendar capped", () => {
    render(<InsightsPage />)
    expect(mockTrends).toHaveBeenLastCalledWith(24, undefined)
    expect(mockCalendar).toHaveBeenLastCalledWith(30, { vehicleId: undefined, limit: 50 })
  })

  it("narrows both the fuel trend and the calendar to the vehicle whose plate is typed, and clears", async () => {
    const user = userEvent.setup()
    render(<InsightsPage />)

    await user.type(screen.getByLabelText("Filter by vehicle"), "cd-5678")
    expect(mockTrends).toHaveBeenLastCalledWith(24, "veh-2")
    expect(mockCalendar).toHaveBeenLastCalledWith(30, { vehicleId: "veh-2", limit: 50 })
    expect(screen.getByText(/Showing CD-5678/)).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Clear" }))
    expect(mockTrends).toHaveBeenLastCalledWith(24, undefined)
  })

  it("says so for an unknown plate and keeps the whole fleet", async () => {
    render(<InsightsPage />)
    await userEvent.setup().type(screen.getByLabelText("Filter by vehicle"), "ZZ-0000")

    expect(screen.getByText(/No vehicle with that plate/)).toBeInTheDocument()
    expect(mockTrends).toHaveBeenLastCalledWith(24, undefined)
  })

  it("lists the calendar in the order the backend sent it", () => {
    mockCalendar.mockReturnValue(done([
      { vehicle_id: "veh-1", plate_number: "NEW-1", service_type: "oil_change", due_date: "2026-10-01", due_km: null, status: "overdue" },
      { vehicle_id: "veh-2", plate_number: "OLD-1", service_type: "oil_change", due_date: "2024-01-01", due_km: null, status: "overdue" },
    ]))
    render(<InsightsPage />)
    const rows = screen.getAllByText(/NEW-1|OLD-1/)
    expect(rows[0]).toHaveTextContent("NEW-1")
  })
})
