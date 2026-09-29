import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { TimelineList } from "@/components/fleet/timeline-list"

describe("TimelineList", () => {
  it("renders one item per entry via the render-prop, keyed correctly", () => {
    const items = [
      { id: "1", label: "First" },
      { id: "2", label: "Second" },
    ]
    render(
      <TimelineList items={items} getKey={(item) => item.id}>
        {(item) => <span>{item.label}</span>}
      </TimelineList>
    )
    expect(screen.getByText("First")).toBeInTheDocument()
    expect(screen.getByText("Second")).toBeInTheDocument()
    expect(screen.getAllByRole("listitem")).toHaveLength(2)
  })

  it("renders an empty list without crashing", () => {
    render(<TimelineList items={[]} getKey={(item: never) => item}>{() => null}</TimelineList>)
    expect(screen.queryAllByRole("listitem")).toHaveLength(0)
  })
})
