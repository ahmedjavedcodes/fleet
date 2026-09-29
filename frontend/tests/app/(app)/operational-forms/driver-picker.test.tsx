import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { IncidentFormDialog } from "@/app/(app)/accountability/_components/incident-form-dialog"
import { FuelLogFormDialog } from "@/app/(app)/fuel/_components/fuel-log-form-dialog"
import { renderWithProviders as render } from "../../../test-utils"

const VEHICLE_ID = "11111111-1111-4111-8111-111111111111"
const OWN_DRIVER_ID = "22222222-2222-4222-8222-222222222222"

const mockUseCurrentUser = vi.fn()
vi.mock("@/lib/auth/use-current-user", () => ({ useCurrentUser: () => mockUseCurrentUser() }))

const mutate = vi.fn()
vi.mock("@/lib/api/incidents", () => ({ useCreateIncident: () => ({ mutate, isPending: false }) }))
vi.mock("@/lib/api/fuel", () => ({ useCreateFuelLog: () => ({ mutate, isPending: false }) }))
vi.mock("@/lib/api/vehicles", () => ({
  useVehicles: () => ({ data: [{ id: VEHICLE_ID, plate_number: "ABC-123" }] }),
}))
vi.mock("@/lib/api/drivers", () => ({
  useDrivers: () => ({ data: [{ id: OWN_DRIVER_ID, full_name: "Sara Khan" }] }),
}))

function signedInAs(role: string) {
  mockUseCurrentUser.mockReturnValue({ role, driverProfile: role === "driver" ? { id: OWN_DRIVER_ID } : null })
}

describe("driver picker visibility", () => {
  beforeEach(() => {
    mutate.mockReset()
  })

  it.each([
    ["incident", () => render(<IncidentFormDialog open onOpenChange={() => {}} defaultVehicleId={VEHICLE_ID} />)],
    ["fuel", () => render(<FuelLogFormDialog open onOpenChange={() => {}} />)],
  ])("%s form: picker is not rendered at all for a driver", (_name, renderForm) => {
    signedInAs("driver")
    renderForm()
    expect(screen.queryByLabelText("Driver")).not.toBeInTheDocument()
    expect(screen.queryByText("Driver")).not.toBeInTheDocument()
  })

  it.each([
    ["incident", () => render(<IncidentFormDialog open onOpenChange={() => {}} defaultVehicleId={VEHICLE_ID} />)],
    ["fuel", () => render(<FuelLogFormDialog open onOpenChange={() => {}} />)],
  ])("%s form: picker is rendered for an admin", (_name, renderForm) => {
    signedInAs("admin")
    renderForm()
    expect(screen.getByText("Driver")).toBeInTheDocument()
  })

  it("incident form: a driver submits without validation errors and is attributed to their own profile", async () => {
    signedInAs("driver")
    render(<IncidentFormDialog open onOpenChange={() => {}} defaultVehicleId={VEHICLE_ID} />)

    await userEvent.type(screen.getByLabelText("Description"), "Scraped the gate")
    await userEvent.click(screen.getByRole("button", { name: "Report incident" }))

    await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1))
    expect(mutate.mock.calls[0]![0]).toMatchObject({
      vehicle_id: VEHICLE_ID,
      driver_id: OWN_DRIVER_ID,
      description: "Scraped the gate",
    })
  })

  it("incident form: an admin with no driver chosen submits with driver_id omitted", async () => {
    signedInAs("admin")
    render(<IncidentFormDialog open onOpenChange={() => {}} defaultVehicleId={VEHICLE_ID} />)

    await userEvent.type(screen.getByLabelText("Description"), "Scraped the gate")
    await userEvent.click(screen.getByRole("button", { name: "Report incident" }))

    await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1))
    expect(mutate.mock.calls[0]![0].driver_id).toBeUndefined()
  })
})
