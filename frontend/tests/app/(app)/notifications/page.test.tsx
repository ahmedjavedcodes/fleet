import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import NotificationsPage from "@/app/(app)/notifications/page"
import { renderWithProviders as render } from "../../../test-utils"

type Row = ReturnType<typeof notification>
const feeds: Record<"warning" | "event", ReturnType<typeof feed>> = { warning: feed([]), event: feed([]) }
const mockMarkRead = vi.fn()
vi.mock("@/lib/api/notifications", () => ({
  useNotificationPages: (type: "warning" | "event") => feeds[type],
  useMarkNotificationRead: () => ({ mutate: mockMarkRead }),
}))

function notification(id: string, type: "warning" | "event", isRead: boolean, title: string, source: "notification" | "incident" = "notification") {
  return {
    id,
    title,
    message: `Details of ${title}`,
    type,
    is_read: isRead,
    created_at: "2026-09-30T09:00:00Z",
    source,
    incident_id: source === "incident" ? id : null,
  }
}
function feed(rows: Row[], extra: Record<string, unknown> = {}) {
  return { data: rows, isPending: false, error: null, refetch: vi.fn(), hasNextPage: false, isFetchingNextPage: false, fetchNextPage: vi.fn(), ...extra }
}

describe("NotificationsPage", () => {
  beforeEach(() => {
    mockMarkRead.mockReset()
    feeds.warning = feed([notification("1", "warning", false, "Severe incident on CD-5678")])
    feeds.event = feed([notification("2", "event", false, "Minor incident on AB-1234"), notification("3", "event", true, "Moderate incident on EF-9012")])
  })

  it("no longer shows the 'not available yet' placeholder for Warnings or Notified events", () => {
    render(<NotificationsPage />)
    expect(screen.queryByText(/isn't available yet/)).not.toBeInTheDocument()
  })

  it("puts warnings in the Warnings tab and events in Notified events, as the backend sorted them", async () => {
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
    feeds.warning = feed([])
    feeds.event = feed([])
    render(<NotificationsPage />)

    expect(screen.getByText("No warnings")).toBeInTheDocument()
    await user.click(screen.getByRole("tab", { name: /Notified events/ }))
    expect(screen.getByText("No notified events")).toBeInTheDocument()
  })

  it("only offers the Warnings and Notified events tabs (no Triggers)", () => {
    render(<NotificationsPage />)
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Warnings1", "Notified events1"])
    expect(screen.queryByRole("tab", { name: /Triggers/ })).not.toBeInTheDocument()
  })

  describe("warnings derived from open incidents", () => {
    it("displays them in the Warnings feed as links to the accountability page, not as something to mark read", async () => {
      const user = userEvent.setup()
      feeds.warning = feed([
        notification("11111111-1111-1111-1111-111111111111", "warning", true, "Open critical incident on KL-1234", "incident"),
        notification("22222222-2222-2222-2222-222222222222", "warning", true, "Open severe incident on MN-5678", "incident"),
      ])
      render(<NotificationsPage />)

      expect(screen.queryByText("No warnings")).not.toBeInTheDocument()
      const first = screen.getByText("Open critical incident on KL-1234").closest("a")!
      expect(first).toHaveAttribute("href", "/accountability")
      expect(screen.getByText("Details of Open severe incident on MN-5678")).toBeInTheDocument()
      expect(within(first).queryByTestId("unread-dot")).not.toBeInTheDocument()

      await user.click(first)
      expect(mockMarkRead).not.toHaveBeenCalled()
    })

    it("lists them alongside stored notifications", () => {
      feeds.warning = feed([
        notification("1", "warning", false, "New severe incident on CD-5678"),
        notification("22222222-2222-2222-2222-222222222222", "warning", true, "Open severe incident on MN-5678", "incident"),
      ])
      render(<NotificationsPage />)

      expect(screen.getByText("New severe incident on CD-5678").closest("button")).toBeInTheDocument()
      expect(screen.getByTestId("incident-notification")).toBeInTheDocument()
    })
  })

  describe("loading a page at a time", () => {
    it("offers Load more when there may be more, and fetches the next page", async () => {
      const user = userEvent.setup()
      const warnings = feed([notification("1", "warning", false, "Severe incident on CD-5678")], { hasNextPage: true })
      feeds.warning = warnings
      render(<NotificationsPage />)

      await user.click(screen.getByRole("button", { name: "Load more" }))
      expect(warnings.fetchNextPage).toHaveBeenCalledTimes(1)
    })

    it("offers no Load more on the last page, and disables it while loading", () => {
      const { unmount } = render(<NotificationsPage />)
      expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument()
      unmount()

      feeds.warning = feed([notification("1", "warning", false, "x")], { hasNextPage: true, isFetchingNextPage: true })
      render(<NotificationsPage />)
      expect(screen.getByRole("button", { name: "Loading…" })).toBeDisabled()
    })
  })
})
