import { render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { Breadcrumbs } from "@/components/primitives/breadcrumbs"

describe("Breadcrumbs", () => {
  afterEach(() => vi.restoreAllMocks())

  it("renders two crumbs that link to the same href without a duplicate-key warning", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {})
    render(
      <Breadcrumbs
        items={[
          { label: "Fleet", href: "/foundation/drivers" },
          { label: "Drivers", href: "/foundation/drivers" },
          { label: "Sara Khan" },
        ]}
      />
    )

    expect(screen.getByRole("link", { name: "Fleet" })).toHaveAttribute("href", "/foundation/drivers")
    expect(screen.getByRole("link", { name: "Drivers" })).toHaveAttribute("href", "/foundation/drivers")
    expect(screen.getByText("Sara Khan")).toBeInTheDocument()
    expect(error.mock.calls.filter((c) => String(c[0]).includes("same key"))).toHaveLength(0)
  })
})
