import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Truck } from "lucide-react"
import { describe, expect, it } from "vitest"
import { KpiTile } from "@/components/primitives/kpi-tile"
import { TooltipProvider } from "@/components/ui/tooltip"

function renderTile(props: Partial<React.ComponentProps<typeof KpiTile>> = {}) {
  return render(
    <TooltipProvider>
      <KpiTile icon={Truck} tone="blue" label="Vehicles" value="24" format="count" {...props} />
    </TooltipProvider>
  )
}

describe("KpiTile", () => {
  it("formats a count as a plain grouped integer", () => {
    renderTile({ value: "1234", format: "count" })
    expect(screen.getByText("1,234")).toBeInTheDocument()
  })

  it("formats money from a decimal string", () => {
    renderTile({ value: "125000.0000", format: "money" })
    expect(screen.getByText(/125,000/)).toBeInTheDocument()
  })

  it("renders a zero value rather than hiding it", () => {
    renderTile({ value: "0", format: "count" })
    expect(screen.getByText("0")).toBeInTheDocument()
  })

  it("renders no hint icon when none is given", () => {
    renderTile()
    expect(screen.queryByRole("button")).not.toBeInTheDocument()
  })

  it("shows the hint text on hover, without nesting a button inside the tile's own link", async () => {
    const user = userEvent.setup()
    const { container } = renderTile({ hint: "Open & investigating", href: "/accountability" })

    // The whole tile is a single <a>; the hint trigger must not be a nested
    // <button> or <a> (invalid HTML — interactive content inside <a>).
    const link = screen.getByRole("link")
    expect(link.querySelector("button, a")).toBeNull()
    expect(container.querySelectorAll("a").length).toBe(1)

    const trigger = screen.getByLabelText("Open & investigating")
    await user.hover(trigger)
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Open & investigating")
  })

  it("wraps the tile in a link to its module page when href is given", () => {
    renderTile({ href: "/foundation/vehicles" })
    expect(screen.getByRole("link")).toHaveAttribute("href", "/foundation/vehicles")
  })
})
