import { render, screen } from "@testing-library/react"
import { Wrench } from "lucide-react"
import { describe, expect, it } from "vitest"
import { DueRow } from "@/components/fleet/due-row"

describe("DueRow", () => {
  it("renders an upcoming item with a warning pill", () => {
    render(<DueRow icon={Wrench} title="Oil change" subtitle="AB-1234" dueText="Due at 21,000 km" status="upcoming" />)
    expect(screen.getByText("Oil change")).toBeInTheDocument()
    expect(screen.getByText("AB-1234")).toBeInTheDocument()
    expect(screen.getByText("Due at 21,000 km")).toBeInTheDocument()
    expect(screen.getByText("Upcoming")).toBeInTheDocument()
  })

  it("renders an overdue item with a destructive pill", () => {
    render(<DueRow icon={Wrench} title="Brake service" dueText="Due 1 Jan 2026" status="overdue" />)
    expect(screen.getByText("Overdue")).toBeInTheDocument()
  })

  it("lets a long title wrap instead of truncating it, while the status side never shrinks", () => {
    render(<DueRow icon={Wrench} title="General inspection and fluid top-up" dueText="Never performed" status="overdue" />)
    const title = screen.getByText("General inspection and fluid top-up")
    expect(title).not.toHaveClass("truncate")
    expect(title).toHaveClass("wrap-break-word")
    expect(title.parentElement).toHaveClass("min-w-0", "flex-1")
    expect(screen.getByText("Never performed").parentElement).toHaveClass("shrink-0")
  })

  it("renders as a link when href is given, and a plain row otherwise", () => {
    const { rerender } = render(<DueRow icon={Wrench} title="Oil change" dueText="—" status="upcoming" href="/foundation/vehicles/abc" />)
    expect(screen.getByRole("link")).toHaveAttribute("href", "/foundation/vehicles/abc")

    rerender(<DueRow icon={Wrench} title="Oil change" dueText="—" status="upcoming" />)
    expect(screen.queryByRole("link")).not.toBeInTheDocument()
  })
})
