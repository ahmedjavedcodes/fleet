import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import AccountabilityPage from "@/app/(app)/accountability/page"
import AssignmentPage from "@/app/(app)/assignment/page"
import FuelPage from "@/app/(app)/fuel/page"
import MaintenancePage from "@/app/(app)/maintenance/page"
import { renderWithProviders as render } from "../../test-utils"

vi.mock("@/lib/auth/use-current-user", () => ({ useCurrentUser: () => ({ role: "admin" }) }))
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }))

const mockMaintenance = vi.fn()
vi.mock("@/lib/api/maintenance", () => ({ useMaintenanceLogs: () => mockMaintenance() }))
vi.mock("@/app/(app)/maintenance/_components/maintenance-form-dialog", () => ({ MaintenanceFormDialog: () => null }))

const mockIncidents = vi.fn()
vi.mock("@/lib/api/incidents", () => ({ useIncidents: () => mockIncidents() }))
const mockReports = vi.fn((): unknown => ({ data: [], isPending: false, error: null, refetch: vi.fn() }))
vi.mock("@/lib/api/driver-reports", () => ({ useDriverReports: () => mockReports() }))
vi.mock("@/app/(app)/accountability/_components/incident-form-dialog", () => ({ IncidentFormDialog: () => null }))
vi.mock("@/app/(app)/accountability/_components/resolve-incident-dialog", () => ({ ResolveIncidentDialog: () => null }))
vi.mock("@/app/(app)/accountability/_components/shift-report-form-dialog", () => ({ ShiftReportFormDialog: () => null }))

const mockFuel = vi.fn()
const mockTrips = vi.fn()
vi.mock("@/lib/api/fuel", () => ({
  useFuelLogs: (params: unknown) => mockFuel(params),
  useFuelSummary: () => ({ data: undefined, isPending: true, error: null, refetch: vi.fn() }),
}))
vi.mock("@/lib/api/trips", () => ({ useTrips: () => mockTrips() }))
vi.mock("@/app/(app)/fuel/_components/fuel-log-form-dialog", () => ({ FuelLogFormDialog: () => null }))
vi.mock("@/app/(app)/fuel/_components/trip-form-dialog", () => ({ TripFormDialog: () => null }))

const mockVehicles = vi.fn()
const mockAssignmentQueries = vi.fn()
vi.mock("@/lib/api/vehicles", () => ({ useVehicles: () => mockVehicles(), getVehicleAssignments: vi.fn() }))
vi.mock("@tanstack/react-query", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-query")>()),
  useQueries: () => mockAssignmentQueries(),
}))
vi.mock("@/components/fleet/assign-release-dialog", () => ({ AssignDriverDialog: () => null, ReleaseDriverFlow: () => null }))

beforeAll(() => {
  Element.prototype.hasPointerCapture = () => false
  Element.prototype.releasePointerCapture = () => {}
  Element.prototype.scrollIntoView = () => {}
})

function query<T>(data: T) {
  return { data, isPending: false, error: null, refetch: vi.fn() }
}

async function pick(user: ReturnType<typeof userEvent.setup>, dropdown: string, option: string) {
  await user.click(screen.getByRole("combobox", { name: dropdown }))
  await user.click(await screen.findByRole("option", { name: option }))
}

describe("Maintenance filters", () => {
  const log = (id: string, plate: string, scale: string, mechanic: string | null, driver: string | null) => ({
    id,
    date: "2026-09-29",
    vehicle_id: `v-${id}`,
    vehicle_plate: plate,
    vehicle_name: "Ford Transit",
    service_types: ["oil_change"],
    service_scale: scale,
    driver_name: driver,
    mechanic_name: mechanic,
    cost: null,
    mechanic_report: null,
  })

  beforeEach(() => {
    mockMaintenance.mockReturnValue(
      query([log("1", "CD-5678", "major", "Hassan", "Bilal Ahmed"), log("2", "AB-1234", "minor", "Imtiaz", "Ali Khan")])
    )
  })

  it("searches by vehicle, mechanic and driver", async () => {
    const user = userEvent.setup()
    render(<MaintenancePage />)
    const box = screen.getByRole("textbox", { name: "Search maintenance" })

    await user.type(box, "cd-5678")
    expect(screen.getByRole("link", { name: "CD-5678" })).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "AB-1234" })).not.toBeInTheDocument()

    await user.clear(box)
    await user.type(box, "imtiaz")
    expect(screen.getByRole("link", { name: "AB-1234" })).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "CD-5678" })).not.toBeInTheDocument()

    await user.clear(box)
    await user.type(box, "bilal")
    expect(screen.getByRole("link", { name: "CD-5678" })).toBeInTheDocument()
  })

  it("filters by service scale", async () => {
    const user = userEvent.setup()
    render(<MaintenancePage />)

    await pick(user, "Filter by service scale", "Major")
    expect(screen.getByRole("link", { name: "CD-5678" })).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "AB-1234" })).not.toBeInTheDocument()
  })
})

describe("Incident filters", () => {
  const incident = (id: string, plate: string, driver: string, severity: string, resolution: string) => ({
    id,
    date: "2026-09-29",
    incident_time: null,
    vehicle_id: `v-${id}`,
    vehicle_plate: plate,
    vehicle_name: "Ford Transit",
    driver_name: driver,
    incident_type: "damage",
    severity,
    description: `Incident ${id}`,
    location_area: null,
    location_description: null,
    attachment_url: null,
    estimated_cost: id === "1" ? "15000.00" : null,
    resolution_status: resolution,
  })

  beforeEach(() => {
    mockIncidents.mockReturnValue(
      query([
        incident("1", "CD-5678", "Bilal Ahmed", "moderate", "open"),
        incident("2", "AB-1234", "Ali Khan", "severe", "resolved"),
        incident("3", "EF-9012", "Omer Farooq", "severe", "open"),
      ])
    )
  })

  it("searches by vehicle and by driver", async () => {
    const user = userEvent.setup()
    render(<AccountabilityPage />)
    const box = screen.getByRole("textbox", { name: "Search incidents" })

    await user.type(box, "ef-9012")
    expect(screen.getByText("Incident 3")).toBeInTheDocument()
    expect(screen.queryByText("Incident 1")).not.toBeInTheDocument()

    await user.clear(box)
    await user.type(box, "ali")
    expect(screen.getByText("Incident 2")).toBeInTheDocument()
    expect(screen.queryByText("Incident 3")).not.toBeInTheDocument()
  })

  it("filters by severity and by status, and the two combine", async () => {
    const user = userEvent.setup()
    render(<AccountabilityPage />)

    await pick(user, "Filter by severity", "Severe")
    expect(screen.queryByText("Incident 1")).not.toBeInTheDocument()
    expect(screen.getByText("Incident 2")).toBeInTheDocument()
    expect(screen.getByText("Incident 3")).toBeInTheDocument()

    await pick(user, "Filter by status", "Open")
    expect(screen.queryByText("Incident 2")).not.toBeInTheDocument()
    expect(screen.getByText("Incident 3")).toBeInTheDocument()
  })

  it("renders the estimated cost when the incident has one", () => {
    render(<AccountabilityPage />)
    expect(screen.getByText(/15,000/)).toBeInTheDocument()
  })
})

describe("Fuel & Trips filters", () => {
  const fuel = (id: string, plate: string, driver: string) => ({
    id,
    date: "2026-09-29",
    vehicle_id: `v-${id}`,
    vehicle_plate: plate,
    vehicle_name: "Toyota Hilux",
    driver_name: driver,
    slip_id: null,
    po_number: null,
    fuel_station_name: null,
    payment_method: null,
    card_used: null,
    odometer_reading: 45000,
    liters_filled: "45.00",
    price_per_liter: "280.00",
    total_cost: "12600.00",
    cost_per_km: id === "f2" ? "25.20" : null,
    is_anomalous: false,
  })
  const trip = (id: string, plate: string, driver: string, start: string) => ({
    id,
    start_time: start,
    end_time: start,
    vehicle_id: `v-${id}`,
    vehicle_plate: plate,
    vehicle_name: "Toyota Hilux",
    driver_name: driver,
    start_odometer: 100,
    end_odometer: 200,
    distance_km: 100,
    fuel_consumed: null,
  })

  beforeEach(() => {
    mockFuel.mockReturnValue(query([fuel("f1", "AB-1234", "Ali Khan"), fuel("f2", "CD-5678", "Bilal Ahmed")]))
    mockTrips.mockReturnValue(
      query([trip("t1", "AB-1234", "Ali Khan", "2026-09-10T08:00:00Z"), trip("t2", "CD-5678", "Bilal Ahmed", "2026-09-29T08:00:00Z")])
    )
  })

  it("searches fuel logs by vehicle and driver", async () => {
    const user = userEvent.setup()
    render(<FuelPage />)
    const box = screen.getByRole("textbox", { name: "Search fuel and trips" })

    await user.type(box, "bilal")
    expect(screen.getByRole("link", { name: "CD-5678" })).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "AB-1234" })).not.toBeInTheDocument()
  })

  it("renders cost per km on a fuel log that has one", () => {
    render(<FuelPage />)
    expect(screen.getByText(/25\.20/)).toBeInTheDocument()
  })

  it("sends the date range to the API for fuel logs", async () => {
    const user = userEvent.setup()
    render(<FuelPage />)

    await user.type(screen.getByLabelText("From date"), "2026-09-01")
    await user.type(screen.getByLabelText("To date"), "2026-09-30")

    expect(mockFuel).toHaveBeenLastCalledWith({ limit: 50, date_from: "2026-09-01", date_to: "2026-09-30" })
  })

  it("filters trips by search and by date range", async () => {
    const user = userEvent.setup()
    render(<FuelPage />)
    await user.click(screen.getByRole("tab", { name: "Trips" }))

    await user.type(screen.getByLabelText("From date"), "2026-09-20")
    expect(screen.getByRole("link", { name: "CD-5678" })).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "AB-1234" })).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Clear" }))
    await user.type(screen.getByRole("textbox", { name: "Search fuel and trips" }), "ali")
    expect(screen.getByRole("link", { name: "AB-1234" })).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "CD-5678" })).not.toBeInTheDocument()
  })
})

describe("Assignment filters", () => {
  const vehicle = (id: string, plate: string, make: string, model: string) => ({ id, plate_number: plate, make, model, current_odometer: 0 })
  const assigned = (driver: string) => ({ data: [{ driver_id: "d", driver_name: driver, released_at: null, assigned_at: "2026-09-29T10:00:00Z" }] })

  beforeEach(() => {
    mockVehicles.mockReturnValue(query([vehicle("v1", "AB-1234", "Toyota", "Hilux"), vehicle("v2", "CD-5678", "Ford", "Transit")]))
    mockAssignmentQueries.mockReturnValue([assigned("Ali Khan"), assigned("Bilal Ahmed")])
  })

  it("searches by plate, by make/model and by current driver", async () => {
    const user = userEvent.setup()
    render(<AssignmentPage />)
    const box = screen.getByRole("textbox", { name: "Search assignments" })

    await user.type(box, "cd-56")
    expect(screen.getByText("CD-5678")).toBeInTheDocument()
    expect(screen.queryByText("AB-1234")).not.toBeInTheDocument()

    await user.clear(box)
    await user.type(box, "hilux")
    expect(screen.getByText("AB-1234")).toBeInTheDocument()
    expect(screen.queryByText("CD-5678")).not.toBeInTheDocument()

    await user.clear(box)
    await user.type(box, "bilal")
    expect(screen.getByText("CD-5678")).toBeInTheDocument()
    expect(screen.queryByText("AB-1234")).not.toBeInTheDocument()
  })

  it("links each plate to its own vehicle page", () => {
    render(<AssignmentPage />)
    expect(screen.getByRole("link", { name: "AB-1234" })).toHaveAttribute("href", "/foundation/vehicles/v1")
  })
})

describe("Shift report filters", () => {
  const report = (id: string, plate: string, shiftDate: string, notes: string | null, issues: string | null) => ({
    id,
    vehicle_id: `v-${id}`,
    vehicle_plate: plate,
    vehicle_name: "Toyota Hilux",
    driver_id: `d-${id}`,
    driver_name: "Ali Khan",
    shift_date: shiftDate,
    vehicle_condition: "good",
    handover_notes: notes,
    issues_reported: issues,
    created_at: "2026-09-30T08:00:00Z",
  })

  beforeEach(() => {
    mockIncidents.mockReturnValue(query([]))
    mockReports.mockReturnValue(
      query([
        report("r1", "AB-1234", "2026-09-10", "Full tank at handover", null),
        report("r2", "CD-5678", "2026-09-29", "Bumper scraped", "Steering feels heavy"),
      ])
    )
  })

  async function openReports(user: ReturnType<typeof userEvent.setup>) {
    render(<AccountabilityPage />)
    await user.click(screen.getByRole("tab", { name: "Shift reports" }))
  }

  it("shows the vehicle for each report and searches by vehicle plate", async () => {
    const user = userEvent.setup()
    await openReports(user)
    expect(screen.getByRole("link", { name: "AB-1234" })).toBeInTheDocument()

    await user.type(screen.getByRole("textbox", { name: "Search shift reports" }), "cd-5678")
    expect(screen.getByRole("link", { name: "CD-5678" })).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "AB-1234" })).not.toBeInTheDocument()
  })

  it("searches handover notes and reported issues", async () => {
    const user = userEvent.setup()
    await openReports(user)
    const box = screen.getByRole("textbox", { name: "Search shift reports" })

    await user.type(box, "full tank")
    expect(screen.getByRole("link", { name: "AB-1234" })).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "CD-5678" })).not.toBeInTheDocument()

    await user.clear(box)
    await user.type(box, "steering")
    expect(screen.getByRole("link", { name: "CD-5678" })).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "AB-1234" })).not.toBeInTheDocument()
  })

  it("filters by shift date range, inclusive of both ends", async () => {
    const user = userEvent.setup()
    await openReports(user)

    await user.type(screen.getByLabelText("From date"), "2026-09-29")
    expect(screen.getByRole("link", { name: "CD-5678" })).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "AB-1234" })).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Clear" }))
    await user.type(screen.getByLabelText("To date"), "2026-09-10")
    expect(screen.getByRole("link", { name: "AB-1234" })).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "CD-5678" })).not.toBeInTheDocument()
  })

  it("says 'No matches' rather than 'no reports yet' when filters exclude everything", async () => {
    const user = userEvent.setup()
    await openReports(user)
    await user.type(screen.getByRole("textbox", { name: "Search shift reports" }), "zzz")
    expect(screen.getByText("No matches")).toBeInTheDocument()
  })
})

describe("Assignment date range", () => {
  const vehicle = (id: string, plate: string) => ({ id, plate_number: plate, make: "Toyota", model: "Hilux", current_odometer: 0 })
  const current = (driver: string, assignedAt: string) => ({
    data: [{ driver_id: "d", driver_name: driver, released_at: null, assigned_at: assignedAt }],
  })

  beforeEach(() => {
    mockVehicles.mockReturnValue(query([vehicle("v1", "AB-1234"), vehicle("v2", "CD-5678"), vehicle("v3", "EF-9012")]))
    // v3 has no current driver.
    mockAssignmentQueries.mockReturnValue([
      current("Ali Khan", "2026-09-05T10:00:00Z"),
      current("Bilal Ahmed", "2026-09-29T10:00:00Z"),
      { data: [] },
    ])
  })

  it("filters vehicles by when the current assignment started", async () => {
    const user = userEvent.setup()
    render(<AssignmentPage />)

    await user.type(screen.getByLabelText("From date"), "2026-09-20")
    expect(screen.getByText("CD-5678")).toBeInTheDocument()
    expect(screen.queryByText("AB-1234")).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Clear" }))
    await user.type(screen.getByLabelText("To date"), "2026-09-10")
    expect(screen.getByText("AB-1234")).toBeInTheDocument()
    expect(screen.queryByText("CD-5678")).not.toBeInTheDocument()
  })

  it("hides unassigned vehicles once a range is set, and shows them again when it is cleared", async () => {
    const user = userEvent.setup()
    render(<AssignmentPage />)
    expect(screen.getByText("EF-9012")).toBeInTheDocument()

    await user.type(screen.getByLabelText("From date"), "2026-01-01")
    expect(screen.queryByText("EF-9012")).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Clear" }))
    expect(screen.getByText("EF-9012")).toBeInTheDocument()
  })

  it("combines the date range with the text search", async () => {
    const user = userEvent.setup()
    render(<AssignmentPage />)

    await user.type(screen.getByLabelText("From date"), "2026-09-01")
    await user.type(screen.getByRole("textbox", { name: "Search assignments" }), "bilal")
    expect(screen.getByText("CD-5678")).toBeInTheDocument()
    expect(screen.queryByText("AB-1234")).not.toBeInTheDocument()
  })
})
