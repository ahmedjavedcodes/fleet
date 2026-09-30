import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import NotificationsPage from "@/app/(app)/notifications/page"
import { renderWithProviders as render } from "../../../test-utils"

const mockNotifications = vi.fn()
const mockMarkRead = vi.fn()
vi.mock("@/lib/api/notifications", () => ({
  useNotifications: () => mockNotifications(),
  useMarkNotificationRead: () => ({ mutate: mockMarkRead }),
}))

function notification(id: string, type: "warning" | "event", isRead: boolean, title: string) {
  return { id, title, message: `Details of ${title}`, type, is_read: isRead, created_at: "2026-09-30T09:00:00Z" }
}
function loaded(data: unknown[]) {
  return { data, isPending: false, error: null, refetch: vi.fn() }
}

describe("NotificationsPage", () => {
  beforeEach(() => {
    mockMarkRead.mockReset()
    mockNotifications.mockReturnValue(
      loaded([
        notification("1", "warning", false, "Severe incident on CD-5678"),
        notification("2", "event", false, "Minor incident on AB-1234"),
        notification("3", "event", true, "Moderate incident on EF-9012"),
      ])
    )
  })

  it("no longer shows the 'not available yet' placeholder for Warnings or Notified events", () => {
    render(<NotificationsPage />)
    expect(screen.queryByText("Warnings isn't available yet")).not.toBeInTheDocument()
    expect(screen.queryByText(/isn't available yet/)).not.toBeInTheDocument()
  })

  it("puts warnings in the Warnings tab and everything else in Notified events, by type", async () => {
    const user = userEvent.setup()
    render(<NotificationsPage />)

    expect(screen.getByText("Severe incident on CD-5678")).toBeInTheDocument()
    expect(screen.queryByText("Minor incident on AB-1234")).not.toBeInTheDocument()

    await user.click(screen.getByRole("tab", { name: /Notified events/ }))
    expect(screen.getByText("Minor incident on AB-1234")).toBeInTheDocument()
    expect(screen.getByText("Moderate incident on EF-9012")).toBeInTheDocument()
    expect(screen.queryByText("Severe incident on CD-5678")).not.toBeInTheDocument()
  })

  it("marks unread notifications with a blue dot and read ones without", async () => {
    const user = userEvent.setup()
    render(<NotificationsPage />)
    await user.click(screen.getByRole("tab", { name: /Notified events/ }))

    const unread = screen.getByText("Minor incident on AB-1234").closest("button")!
    const read = screen.getByText("Moderate incident on EF-9012").closest("button")!
    expect(within(unread).getByTestId("unread-dot")).toBeInTheDocument()
    expect(within(read).queryByTestId("unread-dot")).not.toBeInTheDocument()
  })

  it("shows the unread count on each tab", () => {
    render(<NotificationsPage />)
    expect(within(screen.getByRole("tab", { name: /Warnings/ })).getByLabelText("1 unread")).toBeInTheDocument()
    expect(within(screen.getByRole("tab", { name: /Notified events/ })).getByLabelText("1 unread")).toBeInTheDocument()
  })

  it("marks a notification read when it is clicked, and does nothing for one already read", async () => {
    const user = userEvent.setup()
    render(<NotificationsPage />)

    await user.click(screen.getByText("Severe incident on CD-5678"))
    expect(mockMarkRead).toHaveBeenCalledWith("1")

    mockMarkRead.mockReset()
    await user.click(screen.getByRole("tab", { name: /Notified events/ }))
    await user.click(screen.getByText("Moderate incident on EF-9012"))
    expect(mockMarkRead).not.toHaveBeenCalled()
  })

  it("shows an empty state per tab when it has nothing", async () => {
    const user = userEvent.setup()
    mockNotifications.mockReturnValue(loaded([notification("3", "event", true, "Only an event")]))
    render(<NotificationsPage />)

    expect(screen.getByText("No warnings")).toBeInTheDocument()

    mockNotifications.mockReturnValue(loaded([]))
    render(<NotificationsPage />)
    await user.click(screen.getAllByRole("tab", { name: /Notified events/ })[1]!)
    expect(screen.getByText("No notified events")).toBeInTheDocument()
  })

  it("only offers the Warnings and Notified events tabs (no Triggers)", () => {
    render(<NotificationsPage />)
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Warnings1", "Notified events1"])
    expect(screen.queryByRole("tab", { name: /Triggers/ })).not.toBeInTheDocument()
  })
})
