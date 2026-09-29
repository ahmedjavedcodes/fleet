import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { HealthGauge } from "@/components/charts/health-gauge"

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
  })
})
