import { render } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { AreaTrendChart } from "@/components/charts/area-trend-chart"

type Point = { month: string; totalCost: number; avgCostPerKm: number | null }

const data: Point[] = [
  { month: "2026-01", totalCost: 1000, avgCostPerKm: 12.5 },
  { month: "2026-02", totalCost: 0, avgCostPerKm: null },
  { month: "2026-03", totalCost: 1500, avgCostPerKm: 13.1 },
]

describe("AreaTrendChart", () => {
  it("renders an SVG chart without crashing for a single series", () => {
    const { container } = render(
      <AreaTrendChart data={data} xKey="month" series={[{ key: "totalCost", label: "Fuel cost", color: "var(--chart-1)" }]} />
    )
    expect(container.querySelector("svg")).toBeInTheDocument()
  })

  it("renders a second series on the right axis without crashing, including a null point", () => {
    const { container } = render(
      <AreaTrendChart
        data={data}
        xKey="month"
        series={[
          { key: "totalCost", label: "Fuel cost", color: "var(--chart-1)" },
          { key: "avgCostPerKm", label: "Cost/km", color: "var(--chart-2)", axis: "right" },
        ]}
      />
    )
    expect(container.querySelector("svg")).toBeInTheDocument()
  })

  it("renders with zero data points without crashing", () => {
    const { container } = render(
      <AreaTrendChart data={[]} xKey="month" series={[{ key: "totalCost", label: "Fuel cost", color: "var(--chart-1)" }]} />
    )
    expect(container.querySelector("svg")).toBeInTheDocument()
  })
})
