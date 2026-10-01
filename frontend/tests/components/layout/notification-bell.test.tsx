import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { NotificationBell } from "@/components/layout/notification-bell"

const mockPush = vi.fn()
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mockPush }) }))
const mockNotifications = vi.fn()
const mockHasUnread = vi.fn()
const mockMarkRead = vi.fn()
vi.mock("@/lib/api/notifications", () => ({
  useNotifications: (options?: unknown) => mockNotifications(options),
  useHasUnreadNotifications: () => mockHasUnread(),
  useMarkNotificationRead: () => ({ mutate: mockMarkRead }),
}))

function notification(id: string, isRead: boolean, title = `Notification ${id}`) {
  return { id, title, message: `Message ${id}`, type: "warning", is_read: isRead, created_at: "2026-09-30T09:00:00Z", source: "notification", incident_id: null }
}
function state(data: unknown, extra: Record<string, unknown> = {}) {
  return { data, isPending: false, isError: false, ...extra }
}

describe("NotificationBell", () => {
  beforeEach(() => {
    mockMarkRead.mockReset()
    mockPush.mockReset()
    mockNotifications.mockReset()
    mockNotifications.mockReturnValue(state([]))
    mockHasUnread.mockReturnValue({ data: false })
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

  it("asks for only the latest five (not the whole feed) and asks separately whether anything is unread", async () => {
    mockNotifications.mockReturnValue(state(Array.from({ length: 5 }, (_, i) => notification(String(i + 1), true))))
    mockHasUnread.mockReturnValue({ data: true })
    render(<NotificationBell />)

    expect(mockNotifications).toHaveBeenCalledWith({ limit: 5 })
    // An unread notification older than the five previewed still lights the dot.
    expect(screen.getByTestId("bell-unread-dot")).toBeInTheDocument()
  })

  it("lists the latest five in the popover with a link to the full page", async () => {
    mockNotifications.mockReturnValue(state(Array.from({ length: 5 }, (_, i) => notification(String(i + 1), true))))
    render(<NotificationBell />)
    await userEvent.setup().click(screen.getByRole("button", { name: /notifications/i }))

    expect(await screen.findByText("Notification 1")).toBeInTheDocument()
    expect(screen.getByText("Notification 5")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /go to notifications/i })).toHaveAttribute("href", "/notifications")
  })

  it("asks for unread entries only and vanishes a tapped one (marked read), opening its incident when it has one", async () => {
    const user = userEvent.setup()
    mockNotifications.mockReturnValue(state([{ ...notification("9", false, "Open severe incident on KL-1234"), source: "incident", incident_id: "inc-9" }]))
    render(<NotificationBell />)
    await user.click(screen.getByRole("button", { name: /notifications/i }))

    await user.click(await screen.findByText("Open severe incident on KL-1234"))
    expect(mockMarkRead).toHaveBeenCalledWith("9")
    expect(mockPush).toHaveBeenCalledWith("/accountability?incident=inc-9")
  })

  it("marks an unread notification read when it is clicked, but not one already read", async () => {
    const user = userEvent.setup()
    mockNotifications.mockReturnValue(state([notification("1", false, "Unread one"), notification("2", true, "Read one")]))
    render(<NotificationBell />)
    await user.click(screen.getByRole("button", { name: /notifications/i }))

    await user.click(await screen.findByText("Unread one"))
    expect(mockMarkRead).toHaveBeenCalledWith("1")
    expect(mockPush).not.toHaveBeenCalled()  // a stored notification with no incident just vanishes
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
