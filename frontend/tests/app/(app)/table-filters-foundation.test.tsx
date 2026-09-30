import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import DriversPage from "@/app/(app)/foundation/drivers/page"
import SuppliersPage from "@/app/(app)/foundation/suppliers/page"
import { renderWithProviders as render } from "../../test-utils"

vi.mock("@/lib/auth/use-current-user", () => ({ useCurrentUser: () => ({ role: "fleet_manager" }) }))

const mockDrivers = vi.fn()
vi.mock("@/lib/api/drivers", () => ({ useDrivers: () => mockDrivers(), useDeleteDriver: () => ({ mutate: vi.fn() }) }))
vi.mock("@/app/(app)/foundation/drivers/_components/driver-form-dialog", () => ({ DriverFormDialog: () => null }))

const mockSuppliers = vi.fn()
vi.mock("@/lib/api/suppliers", () => ({ useSuppliers: () => mockSuppliers() }))
vi.mock("@/app/(app)/foundation/suppliers/_components/supplier-form-dialog", () => ({ SupplierFormDialog: () => null }))

beforeAll(() => {
  Element.prototype.hasPointerCapture = () => false
  Element.prototype.releasePointerCapture = () => {}
  Element.prototype.scrollIntoView = () => {}
})

function query<T>(data: T) {
  return { data, isPending: false, error: null, refetch: vi.fn() }
}

function driver(id: string, name: string, license: string, licenseStatus: string | null) {
  return {
    id,
    full_name: name,
    license_number: license,
    license_type: "HTV",
    license_issue_date: "2020-05-15",
    license_expiry: "2030-05-15",
    phone: "+92-300-0000000",
    license_current_status: licenseStatus,
    status: "active",
  }
}

function supplier(id: string, name: string, category: string) {
  return {
    id,
    name,
    category,
    address: null,
    contact_email: null,
    phone: null,
    avg_lead_time_days: null,
    reliability_score: null,
  }
}

async function pick(user: ReturnType<typeof userEvent.setup>, dropdown: string, option: string) {
  await user.click(screen.getByRole("combobox", { name: dropdown }))
  await user.click(await screen.findByRole("option", { name: option }))
}

describe("Drivers filters", () => {
  beforeEach(() => {
    mockDrivers.mockReturnValue(
      query([
        driver("d1", "Ali Khan", "DL-PK-1001", "Active"),
        driver("d2", "Bilal Ahmed", "DL-PK-1002", "Active"),
        driver("d3", "Omer Farooq", "DL-PK-1003", "Renewal Pending"),
      ])
    )
  })

  it("searches by name and by license number", async () => {
    const user = userEvent.setup()
    render(<DriversPage />)
    const box = screen.getByRole("textbox", { name: "Search drivers" })

    await user.type(box, "bilal")
    expect(screen.getByText("Bilal Ahmed")).toBeInTheDocument()
    expect(screen.queryByText("Ali Khan")).not.toBeInTheDocument()

    await user.clear(box)
    await user.type(box, "DL-PK-1003")
    expect(screen.getByText("Omer Farooq")).toBeInTheDocument()
    expect(screen.queryByText("Bilal Ahmed")).not.toBeInTheDocument()
  })

  it("filters by license status, offering only the statuses present in the data", async () => {
    const user = userEvent.setup()
    render(<DriversPage />)

    await user.click(screen.getByRole("combobox", { name: "Filter by license status" }))
    expect(await screen.findByRole("option", { name: "Renewal Pending" })).toBeInTheDocument()
    expect(screen.queryByRole("option", { name: "Suspended" })).not.toBeInTheDocument()
    await user.click(screen.getByRole("option", { name: "Renewal Pending" }))

    expect(screen.getByText("Omer Farooq")).toBeInTheDocument()
    expect(screen.queryByText("Ali Khan")).not.toBeInTheDocument()
  })

  it("combines search with the dropdown, shows 'No matches', and Clear restores everything", async () => {
    const user = userEvent.setup()
    render(<DriversPage />)

    await pick(user, "Filter by license status", "Renewal Pending")
    await user.type(screen.getByRole("textbox", { name: "Search drivers" }), "ali")
    expect(screen.getByText("No matches")).toBeInTheDocument()
    expect(screen.queryByRole("table")).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Clear" }))
    expect(screen.getByText("Ali Khan")).toBeInTheDocument()
    expect(screen.getByText("Omer Farooq")).toBeInTheDocument()
  })
})

describe("Suppliers filters", () => {
  beforeEach(() => {
    mockSuppliers.mockReturnValue(
      query([
        supplier("s1", "Al-Futtaim Motors", "workshop"),
        supplier("s2", "Michelin City", "tire_supplier"),
        supplier("s3", "Global Auto Parts", "parts_supplier"),
      ])
    )
  })

  it("searches by name", async () => {
    const user = userEvent.setup()
    render(<SuppliersPage />)

    await user.type(screen.getByRole("textbox", { name: "Search suppliers" }), "michelin")
    expect(screen.getByText("Michelin City")).toBeInTheDocument()
    expect(screen.queryByText("Al-Futtaim Motors")).not.toBeInTheDocument()
  })

  it("filters by category", async () => {
    const user = userEvent.setup()
    render(<SuppliersPage />)

    await pick(user, "Filter by category", "Workshop")
    expect(screen.getByText("Al-Futtaim Motors")).toBeInTheDocument()
    expect(screen.queryByText("Michelin City")).not.toBeInTheDocument()
    expect(screen.queryByText("Global Auto Parts")).not.toBeInTheDocument()
  })
})

describe("Suppliers calculated columns", () => {
  it("shows reliability as a percentage and lead time in days, and dashes when not yet calculated", () => {
    mockSuppliers.mockReturnValue(
      query([
        { ...supplier("s1", "Al-Futtaim Motors", "workshop"), reliability_score: "0.750", avg_lead_time_days: 7 },
        supplier("s2", "Michelin City", "tire_supplier"),
      ])
    )
    render(<SuppliersPage />)

    expect(screen.getByText("75%")).toBeInTheDocument()
    expect(screen.getByText("7 days")).toBeInTheDocument()
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2)
  })
})
