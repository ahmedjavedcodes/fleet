import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import type { ApiError } from "@/lib/api/errors"
import { ErrorState } from "@/components/states/error-state"

describe("ErrorState", () => {
  it("renders per-kind copy from the §5.3 mapper", () => {
    // Exact strings, not substring regexes — several titles ("Not found")
    // are literal substrings of their own message text ("Vehicle not
    // found"), which would otherwise make both match the same query.
    const cases: [ApiError, string, string][] = [
      [{ kind: "not_found", status: 404, message: "Vehicle not found" }, "Not found", "Vehicle not found"],
      [
        { kind: "conflict", status: 409, message: "Vehicle already assigned" },
        "Out of date",
        "Vehicle already assigned",
      ],
      [{ kind: "rate_limited", status: 429, message: "Try again shortly" }, "Slow down", "Try again shortly"],
      [
        { kind: "unavailable", status: 503, message: "Vector store unavailable" },
        "Temporarily unavailable",
        "Vector store unavailable",
      ],
      [
        { kind: "schema", issues: "bad shape" },
        "Unexpected response",
        "The server returned an unexpected response.",
      ],
      [{ kind: "network" }, "Connection lost", "Couldn't reach the server. Check your connection and try again."],
    ]
    for (const [error, title, body] of cases) {
      const { unmount } = render(<ErrorState error={error} />)
      expect(screen.getByText(title)).toBeInTheDocument()
      expect(screen.getByText(body)).toBeInTheDocument()
      unmount()
    }
  })

  it("shows Retry and calls onRetry when clicked", async () => {
    const onRetry = vi.fn()
    const user = userEvent.setup()
    render(<ErrorState error={{ kind: "not_found", status: 404, message: "Not found" }} onRetry={onRetry} />)
    await user.click(screen.getByRole("button", { name: /retry/i }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it("never shows Retry for a 403 — a permissions fact, not a transient failure", () => {
    const onRetry = vi.fn()
    render(<ErrorState error={{ kind: "forbidden", status: 403, message: "Not enough permissions" }} onRetry={onRetry} />)
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument()
  })

  it("omits Retry entirely when no onRetry is given", () => {
    render(<ErrorState error={{ kind: "server", status: 500 }} />)
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument()
  })
})
