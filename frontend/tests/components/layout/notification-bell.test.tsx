import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { NotificationBell } from "@/components/layout/notification-bell"

const mockNotifications = vi.fn()
const mockMarkRead = vi.fn()
vi.mock("@/lib/api/notifications", () => ({
  useNotifications: () => mockNotifications(),
  useMarkNotificationRead: () => ({ mutate: mockMarkRead }),
}))

function notification(id: string, isRead: boolean, title = `Notification ${id}`) {
  return { id, title, message: `Message ${id}`, type: "warning", is_read: isRead, created_at: "2026-09-30T09:00:00Z" }
}
function state(data: unknown, extra: Record<string, unknown> = {}) {
  return { data, isPending: false, isError: false, ...extra }
}

describe("NotificationBell", () => {
  beforeEach(() => {
    mockMarkRead.mockReset()
    mockNotifications.mockReturnValue(state([]))
  })

  it("shows a blue unread dot, never a count, when something is unread", () => {
    mockNotifications.mockReturnValue(state([notification("1", false), notification("2", false)]))
    render(<NotificationBell />)

    expect(screen.getByTestId("bell-unread-dot")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Notifications (unread)" })).toBeInTheDocument()
    expect(screen.queryByText(/^\d+\+?$/)).not.toBeInTheDocument()
  })

  it("shows no dot when everything is read or there is nothing", () => {
    mockNotifications.mockReturnValue(state([notification("1", true)]))
    const { unmount } = render(<NotificationBell />)
    expect(screen.queryByTestId("bell-unread-dot")).not.toBeInTheDocument()
    unmount()

    mockNotifications.mockReturnValue(state([]))
    render(<NotificationBell />)
    expect(screen.queryByTestId("bell-unread-dot")).not.toBeInTheDocument()
  })

  it("lists the latest five in the popover with a link to the full page", async () => {
    mockNotifications.mockReturnValue(state(Array.from({ length: 7 }, (_, i) => notification(String(i + 1), true))))
    render(<NotificationBell />)
    await userEvent.setup().click(screen.getByRole("button", { name: /notifications/i }))

    expect(await screen.findByText("Notification 1")).toBeInTheDocument()
    expect(screen.getByText("Notification 5")).toBeInTheDocument()
    expect(screen.queryByText("Notification 6")).not.toBeInTheDocument()
    expect(screen.getByRole("link", { name: /go to notifications/i })).toHaveAttribute("href", "/notifications")
  })

  it("marks an unread notification read when it is clicked, but not one already read", async () => {
    const user = userEvent.setup()
    mockNotifications.mockReturnValue(state([notification("1", false, "Unread one"), notification("2", true, "Read one")]))
    render(<NotificationBell />)
    await user.click(screen.getByRole("button", { name: /notifications/i }))

    await user.click(await screen.findByText("Read one"))
    expect(mockMarkRead).not.toHaveBeenCalled()

    await user.click(screen.getByText("Unread one"))
    expect(mockMarkRead).toHaveBeenCalledWith("1")
  })

  it("says so when it is empty or fails to load", async () => {
    const user = userEvent.setup()
    render(<NotificationBell />)
    await user.click(screen.getByRole("button", { name: /notifications/i }))
    expect(await screen.findByText("You're all caught up.")).toBeInTheDocument()
  })

  it("shows a load failure instead of an empty state", async () => {
    mockNotifications.mockReturnValue(state(undefined, { isError: true }))
    render(<NotificationBell />)
    await userEvent.setup().click(screen.getByRole("button", { name: /notifications/i }))
    expect(await screen.findByText("Couldn't load notifications.")).toBeInTheDocument()
  })
})
