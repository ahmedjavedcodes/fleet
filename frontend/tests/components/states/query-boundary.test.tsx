import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { QueryRegion } from "@/components/states/query-boundary"

function fakeQuery<T>(overrides: Partial<{ data: T; isPending: boolean; error: unknown; refetch: () => unknown }>) {
  return { data: undefined as T | undefined, isPending: false, error: null, refetch: vi.fn(), ...overrides }
}

describe("QueryRegion", () => {
  it("loading: renders the skeleton, not children", () => {
    render(
      <QueryRegion query={fakeQuery({ isPending: true })} skeleton={<div>Loading…</div>}>
        {() => <div>Content</div>}
      </QueryRegion>
    )
    expect(screen.getByText("Loading…")).toBeInTheDocument()
    expect(screen.queryByText("Content")).not.toBeInTheDocument()
  })

  it("error (403): renders AccessDenied for just this region, not the generic ErrorState", () => {
    render(
      <QueryRegion
        query={fakeQuery({ error: { kind: "forbidden", status: 403, message: "Not enough permissions" } })}
        skeleton={<div>Loading…</div>}
        areaLabel="fleet health"
      >
        {() => <div>Content</div>}
      </QueryRegion>
    )
    expect(screen.getByText("You don't have access to fleet health")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument()
  })

  it("error (other): renders ErrorState with Retry wired to query.refetch", async () => {
    const refetch = vi.fn()
    const user = userEvent.setup()
    render(
      <QueryRegion
        query={fakeQuery({ error: { kind: "not_found", status: 404, message: "Not found" }, refetch })}
        skeleton={<div>Loading…</div>}
      >
        {() => <div>Content</div>}
      </QueryRegion>
    )
    await user.click(screen.getByRole("button", { name: /retry/i }))
    expect(refetch).toHaveBeenCalledTimes(1)
  })

  it("treats a non-ApiError as a network error rather than crashing", () => {
    render(
      <QueryRegion query={fakeQuery({ error: new Error("boom") })} skeleton={<div>Loading…</div>}>
        {() => <div>Content</div>}
      </QueryRegion>
    )
    expect(screen.getByText("Connection lost")).toBeInTheDocument()
  })

  it("empty: renders the empty node when isEmpty(data) is true", () => {
    render(
      <QueryRegion
        query={fakeQuery({ data: [] })}
        skeleton={<div>Loading…</div>}
        empty={<div>Nothing here</div>}
        isEmpty={(data: unknown[]) => data.length === 0}
      >
        {(data: unknown[]) => <div>{data.length} items</div>}
      </QueryRegion>
    )
    expect(screen.getByText("Nothing here")).toBeInTheDocument()
  })

  it("data: renders children with the resolved data when not empty", () => {
    render(
      <QueryRegion
        query={fakeQuery({ data: [1, 2, 3] })}
        skeleton={<div>Loading…</div>}
        empty={<div>Nothing here</div>}
        isEmpty={(data: unknown[]) => data.length === 0}
      >
        {(data: unknown[]) => <div>{data.length} items</div>}
      </QueryRegion>
    )
    expect(screen.getByText("3 items")).toBeInTheDocument()
  })
})
