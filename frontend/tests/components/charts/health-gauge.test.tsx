import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { HealthGauge } from "@/components/charts/health-gauge"

function arc() {
  return screen.queryByTestId("gauge-value")
}

describe("HealthGauge", () => {
  it("renders the score and label for a high score", () => {
    render(<HealthGauge score={100} />)
    const meter = screen.getByRole("meter")
    expect(meter).toHaveAttribute("aria-valuenow", "100")
    expect(meter).toHaveAttribute("aria-valuetext", "100 out of 100 — Good")
    expect(screen.getByText("100")).toBeInTheDocument()
  })

  it("renders a mid-range score as Fair", () => {
    render(<HealthGauge score={60} />)
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuetext", "60 out of 100 — Fair")
  })

  it("renders a low score as Poor", () => {
    render(<HealthGauge score={0} />)
    const meter = screen.getByRole("meter")
    expect(meter).toHaveAttribute("aria-valuenow", "0")
    expect(meter).toHaveAttribute("aria-valuetext", "0 out of 100 — Poor")
  })

  it("renders 'n/a', never 0, when the score is null", () => {
    render(<HealthGauge score={null} />)
    const meter = screen.getByRole("meter")
    expect(meter).not.toHaveAttribute("aria-valuenow")
    expect(meter).toHaveAttribute("aria-valuetext", "Not available")
    expect(screen.getByText("n/a")).toBeInTheDocument()
    expect(screen.queryByText("0")).not.toBeInTheDocument()
    expect(arc()).not.toBeInTheDocument()
  })

  it.each([
    [100, "100 100"],
    [80, "80 100"],
    [63, "63 100"],
    [1, "1 100"],
  ])("maps a score of %i to a stroke-dasharray of '%s' over a path normalised to 100", (score, dash) => {
    render(<HealthGauge score={score} />)
    expect(arc()).toHaveAttribute("pathLength", "100")
    expect(arc()).toHaveAttribute("stroke-dasharray", dash)
  })

  it("draws no value arc at 0, and clamps scores outside 0-100", () => {
    const { unmount } = render(<HealthGauge score={0} />)
    expect(arc()).not.toBeInTheDocument()
    unmount()

    render(<HealthGauge score={140} />)
    expect(arc()).toHaveAttribute("stroke-dasharray", "100 100")
  })

  it.each([
    [95, "var(--success)"],
    [80, "var(--success)"],
    [79, "var(--warning)"],
    [50, "var(--warning)"],
    [49, "var(--destructive)"],
    [5, "var(--destructive)"],
  ])("colours a score of %i with %s, matching its badge", (score, colour) => {
    render(<HealthGauge score={score} />)
    expect(arc()).toHaveAttribute("stroke", colour)
  })
})
