import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"
import { NotificationBell } from "@/components/layout/notification-bell"

describe("NotificationBell", () => {
  it("renders no badge or count — the notifications API doesn't exist yet (CLAUDE.md §3, §5.5)", () => {
    const { container } = render(<NotificationBell />)
    // No numeral anywhere near the trigger, and no element carrying a
    // badge-like slot/class.
    expect(screen.queryByText(/^\d+\+?$/)).not.toBeInTheDocument()
    expect(container.querySelector('[data-slot="avatar-badge"]')).not.toBeInTheDocument()
  })

  it("opens to an honest 'not available yet' message with a link to /notifications", async () => {
    const user = userEvent.setup()
    render(<NotificationBell />)
    await user.click(screen.getByRole("button", { name: /notifications/i }))
    expect(await screen.findByText(/notifications aren't available yet/i)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /go to notifications/i })).toHaveAttribute("href", "/notifications")
  })
})
