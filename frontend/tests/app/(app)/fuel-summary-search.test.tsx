import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import FuelPage from "@/app/(app)/fuel/page"
import { renderWithProviders as render } from "../../test-utils"

vi.mock("@/lib/auth/use-current-user", () => ({ useCurrentUser: () => ({ role: "admin" }) }))
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }))

const done = (data: unknown) => ({ data, isPending: false, error: null, refetch: vi.fn() })
const row = (id: string, plate: string, name: string, drivers: string[]) => ({
  vehicle_id: id, plate_number: plate, vehicle_name: name, driver_names: drivers, fill_count: 3, first_fill_date: "2026-10-01",
  last_fill_date: "2026-10-02", total_cost: "1000.00", total_liters: "40.00", avg_cost_per_km: "25.00",
})
vi.mock("@/lib/api/fuel", () => ({
  useFuelLogs: () => done([]),
  useFuelSummary: () =>
    done({
      total_cost: "3000.00", total_liters: "120.00", avg_cost_per_km: "25.00",
      by_vehicle: [row("v1", "AB-1234", "Toyota Hilux", ["Omar Farooq"]), row("v2", "CD-5678", "Ford Transit", ["Zainab Qureshi"]), row("v3", "EF-9012", "Isuzu D-Max", [])],
    }),
}))
vi.mock("@/lib/api/trips", () => ({ useTrips: () => done([]) }))
vi.mock("@/app/(app)/fuel/_components/fuel-log-form-dialog", () => ({ FuelLogFormDialog: () => null }))
vi.mock("@/app/(app)/fuel/_components/trip-form-dialog", () => ({ TripFormDialog: () => null }))

async function openSummary() {
  const user = userEvent.setup()
  render(<FuelPage />)
  await user.click(screen.getByRole("tab", { name: "Summary" }))
  return { user, box: screen.getByLabelText("Search the fuel summary") }
}

describe("Fuel summary search", () => {
  it("lists every vehicle until something is typed", async () => {
    await openSummary()
    for (const plate of ["AB-1234", "CD-5678", "EF-9012"]) expect(screen.getByText(plate)).toBeInTheDocument()
  })

  it("filters by plate, vehicle name or driver, and says so when nothing matches", async () => {
    const { user, box } = await openSummary()

    await user.type(box, "cd-5678")
    expect(screen.getByText("CD-5678")).toBeInTheDocument()
    expect(screen.queryByText("AB-1234")).not.toBeInTheDocument()

    await user.clear(box)
    await user.type(box, "hilux")
    expect(screen.getByText("AB-1234")).toBeInTheDocument()
    expect(screen.queryByText("CD-5678")).not.toBeInTheDocument()

    await user.clear(box)
    await user.type(box, "zainab")
    expect(screen.getByText("CD-5678")).toBeInTheDocument()
    expect(screen.queryByText("EF-9012")).not.toBeInTheDocument()

    await user.clear(box)
    await user.type(box, "nobody")
    expect(screen.getByText("No matches")).toBeInTheDocument()
  })
})
