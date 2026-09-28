import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import type { UserRole } from "@/lib/schemas/enums"
import { TooltipProvider } from "@/components/ui/tooltip"
import { SidebarNav } from "./sidebar-nav"

const mockUseCurrentUser = vi.fn()
vi.mock("@/lib/auth/use-current-user", () => ({
  useCurrentUser: () => mockUseCurrentUser(),
}))

let mockPathname = "/dashboard"
vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
}))

function mockRole(role: UserRole | null, isPending = false) {
  mockUseCurrentUser.mockReturnValue({ role, isPending })
}

describe("SidebarNav", () => {
  it("renders skeleton rows, not the real list, while the role is loading", () => {
    mockRole(null, true)
    render(<SidebarNav collapsed={false} />)
    expect(screen.queryByText("Overview")).not.toBeInTheDocument()
    expect(screen.getByLabelText(/loading navigation/i)).toBeInTheDocument()
  })

  it("admin sees every group and item", () => {
    mockPathname = "/dashboard"
    mockRole("admin")
    render(<SidebarNav collapsed={false} />)
    for (const label of [
      "Overview",
      "AI Assistant",
      "Vehicles",
      "Drivers",
      "Suppliers",
      "Assignment",
      "Fuel & Trips",
      "Maintenance",
      "Accountability",
      "Documents",
      "Notifications",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    // "Insights" is both a group label and its sole item's label — assert
    // both copies exist instead of a single ambiguous getByText.
    expect(screen.getAllByText("Insights")).toHaveLength(2)
  })

  it("driver doesn't see Maintenance or Insights, and hides their now-empty groups", () => {
    mockPathname = "/dashboard"
    mockRole("driver")
    render(<SidebarNav collapsed={false} />)
    expect(screen.queryByText("Maintenance")).not.toBeInTheDocument()
    // Insights is the Insights group's only item — the whole group,
    // including its label, must disappear (plans/03 §3).
    expect(screen.queryByText("Insights")).not.toBeInTheDocument()
    expect(screen.getByText("Fuel & Trips")).toBeInTheDocument()
  })

  it("mechanic sees Maintenance but not Fuel & Trips or Assignment", () => {
    mockPathname = "/dashboard"
    mockRole("mechanic")
    render(<SidebarNav collapsed={false} />)
    expect(screen.getByText("Maintenance")).toBeInTheDocument()
    expect(screen.queryByText("Fuel & Trips")).not.toBeInTheDocument()
    expect(screen.queryByText("Assignment")).not.toBeInTheDocument()
  })

  it("marks the active item with aria-current, using a prefix match", () => {
    mockPathname = "/maintenance/abc-123"
    mockRole("admin")
    render(<SidebarNav collapsed={false} />)
    const maintenanceLink = screen.getByRole("link", { name: /maintenance/i })
    expect(maintenanceLink).toHaveAttribute("aria-current", "page")
    const fuelLink = screen.getByRole("link", { name: /fuel & trips/i })
    expect(fuelLink).not.toHaveAttribute("aria-current")
  })

  it("collapsed mode hides labels and group headings but keeps icons reachable", () => {
    mockPathname = "/dashboard"
    mockRole("admin")
    render(
      <TooltipProvider>
        <SidebarNav collapsed />
      </TooltipProvider>
    )
    expect(screen.queryByText("Overview")).not.toBeInTheDocument()
    expect(screen.queryByText("Main Menu")).not.toBeInTheDocument()
    expect(screen.getAllByRole("link").length).toBeGreaterThan(0)
  })
})
