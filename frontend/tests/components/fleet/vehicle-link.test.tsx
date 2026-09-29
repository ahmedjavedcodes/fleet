import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { VehicleLink } from "@/components/fleet/vehicle-link"

describe("VehicleLink", () => {
  it("shows the plate number as the link to the vehicle detail page, never 'View vehicle'", () => {
    render(<VehicleLink vehicleId="v-1" plate="LEA-1001" name="Toyota Hilux" />)
    const link = screen.getByRole("link", { name: "LEA-1001" })
    expect(link).toHaveAttribute("href", "/foundation/vehicles/v-1")
    expect(screen.getByText("Toyota Hilux")).toBeInTheDocument()
    expect(screen.queryByText(/view vehicle/i)).not.toBeInTheDocument()
  })

  it("renders a dash instead of an empty link when there is no plate", () => {
    render(<VehicleLink vehicleId="v-1" plate={null} />)
    expect(screen.queryByRole("link")).not.toBeInTheDocument()
    expect(screen.getByText("—")).toBeInTheDocument()
  })
})
