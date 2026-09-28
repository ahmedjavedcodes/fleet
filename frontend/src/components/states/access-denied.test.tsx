import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { AccessDenied } from "./access-denied"

describe("AccessDenied", () => {
  it("names the area and links back to the dashboard", () => {
    render(<AccessDenied area="Maintenance" allowedRoles={["admin"]} />)
    expect(screen.getByText("You don't have access to Maintenance")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /back to dashboard/i })).toHaveAttribute("href", "/dashboard")
  })

  it("formats a role-aware hint for two roles", () => {
    render(<AccessDenied area="Maintenance" allowedRoles={["admin", "fleet_manager"]} />)
    expect(screen.getByText("Available to Admin and Fleet Manager.")).toBeInTheDocument()
  })

  it("formats a role-aware hint for three roles with an Oxford-free list", () => {
    render(<AccessDenied area="Maintenance" allowedRoles={["admin", "fleet_manager", "mechanic"]} />)
    expect(screen.getByText("Available to Admin, Fleet Manager and Mechanic.")).toBeInTheDocument()
  })

  it("omits the hint entirely when allowedRoles is null or empty", () => {
    const { rerender } = render(<AccessDenied area="Insights" allowedRoles={null} />)
    expect(screen.queryByText(/available to/i)).not.toBeInTheDocument()
    rerender(<AccessDenied area="Insights" allowedRoles={[]} />)
    expect(screen.queryByText(/available to/i)).not.toBeInTheDocument()
  })
})
