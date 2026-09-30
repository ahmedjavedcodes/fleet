import { screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { IncidentFormDialog } from "@/app/(app)/accountability/_components/incident-form-dialog"
import { TripFormDialog } from "@/app/(app)/fuel/_components/trip-form-dialog"
import { renderWithProviders as render } from "../../../test-utils"

const VEHICLE_ID = "11111111-1111-4111-8111-111111111111"
const DRIVER_ID = "22222222-2222-4222-8222-222222222222"

// One stable object: the forms reset on driverProfile identity changes, so a
// fresh object per render would loop forever.
const CURRENT_USER = { role: "driver", driverProfile: { id: DRIVER_ID } }
vi.mock("@/lib/auth/use-current-user", () => ({ useCurrentUser: () => CURRENT_USER }))
vi.mock("@/lib/api/vehicles", () => ({ useVehicles: () => ({ data: [{ id: VEHICLE_ID, plate_number: "ABC-123" }] }) }))
vi.mock("@/lib/api/drivers", () => ({ useDrivers: () => ({ data: [] }) }))

const createTrip = vi.fn()
vi.mock("@/lib/api/trips", () => ({ useCreateTrip: () => ({ mutate: createTrip, isPending: false }) }))

const createIncident = vi.fn()
vi.mock("@/lib/api/incidents", () => ({ useCreateIncident: () => ({ mutate: createIncident, isPending: false }) }))

const uploadImage = vi.fn()
vi.mock("@/lib/api/uploads", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/uploads")>()),
  useUploadImage: () => ({ mutateAsync: uploadImage, isPending: false }),
}))

beforeAll(() => {
  Element.prototype.hasPointerCapture = () => false
  Element.prototype.releasePointerCapture = () => {}
  Element.prototype.scrollIntoView = () => {}
  URL.createObjectURL = vi.fn(() => "blob:preview")
  URL.revokeObjectURL = vi.fn()
})

beforeEach(() => {
  createTrip.mockReset()
  createIncident.mockReset()
  uploadImage.mockReset()
})

describe("TripFormDialog fuel used", () => {
  async function fillTrip(fuel?: string) {
    await userEvent.click(screen.getByRole("combobox", { name: "Vehicle" }))
    await userEvent.click(await screen.findByRole("option", { name: "ABC-123" }))
    await userEvent.clear(screen.getByLabelText("Start odometer"))
    await userEvent.type(screen.getByLabelText("Start odometer"), "45000")
    await userEvent.clear(screen.getByLabelText("End odometer"))
    await userEvent.type(screen.getByLabelText("End odometer"), "45250")
    if (fuel !== undefined) await userEvent.type(screen.getByLabelText(/Fuel used \(L\)/), fuel)
    await userEvent.click(screen.getByRole("button", { name: "Log trip" }))
  }

  it("sends the entered litres as fuel_consumed", async () => {
    render(<TripFormDialog open onOpenChange={() => {}} />)
    await fillTrip("32.5")
    await waitFor(() => expect(createTrip).toHaveBeenCalledTimes(1))
    expect(createTrip.mock.calls[0]![0]).toMatchObject({ start_odometer: 45000, end_odometer: 45250, fuel_consumed: 32.5 })
  })

  it("treats the field as optional", async () => {
    render(<TripFormDialog open onOpenChange={() => {}} />)
    await fillTrip()
    await waitFor(() => expect(createTrip).toHaveBeenCalledTimes(1))
    expect(createTrip.mock.calls[0]![0].fuel_consumed).toBeUndefined()
  })

  it("rejects negative fuel", async () => {
    render(<TripFormDialog open onOpenChange={() => {}} />)
    await fillTrip("-3")
    expect(await screen.findByText(/greater than or equal to 0/i)).toBeInTheDocument()
    expect(createTrip).not.toHaveBeenCalled()
  })
})

describe("IncidentFormDialog image attachment", () => {
  async function submitWith(file?: File) {
    await userEvent.type(screen.getByLabelText("Description"), "Scraped the gate")
    if (file) await userEvent.upload(screen.getByLabelText(/drag an image here/i), file)
    await userEvent.click(screen.getByRole("button", { name: "Report incident" }))
  }

  it("no longer offers a free-text attachment URL field", () => {
    render(<IncidentFormDialog open onOpenChange={() => {}} defaultVehicleId={VEHICLE_ID} />)
    expect(screen.queryByLabelText("Attachment URL")).not.toBeInTheDocument()
    expect(screen.getByText(/drag an image here/i)).toBeInTheDocument()
  })

  it("uploads the chosen image first and submits the returned url as attachment_url", async () => {
    uploadImage.mockResolvedValue("/uploads/incidents/abc.jpg")
    const file = new File(["x"], "gate.jpg", { type: "image/jpeg" })
    render(<IncidentFormDialog open onOpenChange={() => {}} defaultVehicleId={VEHICLE_ID} />)

    await submitWith(file)

    await waitFor(() => expect(createIncident).toHaveBeenCalledTimes(1))
    expect(uploadImage).toHaveBeenCalledWith(file)
    expect(createIncident.mock.calls[0]![0]).toMatchObject({
      description: "Scraped the gate",
      attachment_url: "/uploads/incidents/abc.jpg",
    })
  })

  it("submits without attachment_url when no image is chosen and never calls the upload", async () => {
    render(<IncidentFormDialog open onOpenChange={() => {}} defaultVehicleId={VEHICLE_ID} />)

    await submitWith()

    await waitFor(() => expect(createIncident).toHaveBeenCalledTimes(1))
    expect(uploadImage).not.toHaveBeenCalled()
    expect(createIncident.mock.calls[0]![0].attachment_url).toBeUndefined()
  })

  it("does not create the incident when the upload fails", async () => {
    uploadImage.mockRejectedValue({ kind: "bad_request", status: 400, message: "Only JPEG and PNG images are allowed" })
    render(<IncidentFormDialog open onOpenChange={() => {}} defaultVehicleId={VEHICLE_ID} />)

    await submitWith(new File(["x"], "gate.jpg", { type: "image/jpeg" }))

    await waitFor(() => expect(uploadImage).toHaveBeenCalledTimes(1))
    expect(createIncident).not.toHaveBeenCalled()
  })
})
