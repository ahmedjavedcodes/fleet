import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeAll, describe, expect, it, vi } from "vitest"
import { FilterBar } from "@/components/primitives/filter-bar"

// Radix Select needs these pointer/scroll APIs, which jsdom lacks.
beforeAll(() => {
  Element.prototype.hasPointerCapture = () => false
  Element.prototype.releasePointerCapture = () => {}
  Element.prototype.scrollIntoView = () => {}
})

const SEVERITY = {
  label: "Filter by severity",
  allLabel: "All severities",
  options: [
    { value: "minor", label: "Minor" },
    { value: "severe", label: "Severe" },
  ],
}

describe("FilterBar", () => {
  it("reports typed search text", async () => {
    const onSearchChange = vi.fn()
    render(<FilterBar search="" onSearchChange={onSearchChange} searchLabel="Search x" searchPlaceholder="Search…" />)

    await userEvent.setup().type(screen.getByRole("textbox", { name: "Search x" }), "a")
    expect(onSearchChange).toHaveBeenCalledWith("a")
  })

  it("reports the option picked from a dropdown", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <FilterBar search="" onSearchChange={vi.fn()} searchLabel="Search x" searchPlaceholder="Search…" selects={[{ ...SEVERITY, value: "all", onChange }]} />
    )

    await user.click(screen.getByRole("combobox", { name: "Filter by severity" }))
    await user.click(await screen.findByRole("option", { name: "Severe" }))
    expect(onChange).toHaveBeenCalledWith("severe")
  })

  it("reports each end of the date range without dropping the other", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <FilterBar
        search=""
        onSearchChange={vi.fn()}
        searchLabel="Search x"
        searchPlaceholder="Search…"
        dateRange={{ from: "2026-09-01", to: "", onChange }}
      />
    )

    await user.type(screen.getByLabelText("To date"), "2026-09-30")
    expect(onChange).toHaveBeenLastCalledWith({ from: "2026-09-01", to: "2026-09-30" })
  })

  it("shows Clear only when a filter is active, and resets all of them", async () => {
    const user = userEvent.setup()
    const onSearchChange = vi.fn()
    const onSeverity = vi.fn()
    const onRange = vi.fn()
    const props = { onSearchChange, searchLabel: "Search x", searchPlaceholder: "Search…" }

    const { rerender } = render(
      <FilterBar {...props} search="" selects={[{ ...SEVERITY, value: "all", onChange: onSeverity }]} dateRange={{ from: "", to: "", onChange: onRange }} />
    )
    expect(screen.queryByRole("button", { name: "Clear" })).not.toBeInTheDocument()

    rerender(
      <FilterBar {...props} search="ali" selects={[{ ...SEVERITY, value: "severe", onChange: onSeverity }]} dateRange={{ from: "2026-09-01", to: "", onChange: onRange }} />
    )
    await user.click(screen.getByRole("button", { name: "Clear" }))

    expect(onSearchChange).toHaveBeenCalledWith("")
    expect(onSeverity).toHaveBeenCalledWith("all")
    expect(onRange).toHaveBeenCalledWith({ from: "", to: "" })
  })
})
