import { render, screen } from "@testing-library/react"
import { Fuel } from "lucide-react"
import { describe, expect, it } from "vitest"
import { EmptyState } from "./empty-state"

describe("EmptyState", () => {
  it("renders the title and description", () => {
    render(<EmptyState icon={Fuel} title="No fuel logs yet" description="Log your first fuel entry." />)
    expect(screen.getByText("No fuel logs yet")).toBeInTheDocument()
    expect(screen.getByText("Log your first fuel entry.")).toBeInTheDocument()
  })

  it("renders no action when the caller doesn't pass one (a role that can't act)", () => {
    render(<EmptyState icon={Fuel} title="No fuel logs yet" description="…" />)
    expect(screen.queryByRole("button")).not.toBeInTheDocument()
    expect(screen.queryByRole("link")).not.toBeInTheDocument()
  })

  it("renders the action when the caller passes one (a role that can act)", () => {
    render(
      <EmptyState
        icon={Fuel}
        title="No fuel logs yet"
        description="…"
        action={<button type="button">Log fuel</button>}
      />
    )
    expect(screen.getByRole("button", { name: /log fuel/i })).toBeInTheDocument()
  })
})
