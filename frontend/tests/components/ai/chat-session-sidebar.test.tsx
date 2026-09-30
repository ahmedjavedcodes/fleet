import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { ChatSessionSidebar } from "@/components/ai/chat-session-sidebar"
import type { ChatSessionSummary } from "@/lib/schemas/chat"

function session(id: string, title: string): ChatSessionSummary {
  return { id, title, message_count: 2, created_at: "2026-09-30T08:00:00Z", updated_at: "2026-09-30T09:00:00Z" }
}

const SESSIONS = [session("s1", "Overdue service report"), session("s2", "Fuel costs this month")]

function setup(overrides: Partial<React.ComponentProps<typeof ChatSessionSidebar>> = {}) {
  const props = {
    sessions: SESSIONS,
    isPending: false,
    isError: false,
    onRetry: vi.fn(),
    activeId: null as string | null,
    onSelect: vi.fn(),
    onNew: vi.fn(),
    onRename: vi.fn(),
    onDelete: vi.fn(),
    ...overrides,
  }
  render(<ChatSessionSidebar {...props} />)
  return props
}

describe("ChatSessionSidebar", () => {
  it("has a prominent New chat button that starts a fresh thread", async () => {
    const props = setup()
    await userEvent.setup().click(screen.getByRole("button", { name: "New chat" }))
    expect(props.onNew).toHaveBeenCalledTimes(1)
  })

  it("lists each conversation by title, and picking one selects it", async () => {
    const props = setup()
    expect(screen.getByText("Overdue service report")).toBeInTheDocument()
    expect(screen.getByText("Fuel costs this month")).toBeInTheDocument()

    await userEvent.setup().click(screen.getByRole("button", { name: /^Fuel costs this month/ }))
    expect(props.onSelect).toHaveBeenCalledWith("s2")
  })

  it("marks only the active conversation as current", () => {
    setup({ activeId: "s2" })
    expect(screen.getByRole("button", { name: /^Fuel costs this month/ })).toHaveAttribute("aria-current", "true")
    expect(screen.getByRole("button", { name: /^Overdue service report/ })).not.toHaveAttribute("aria-current")
  })

  it("shows a loading state, an error with retry, and an empty state", async () => {
    const { unmount } = render(
      <ChatSessionSidebar sessions={undefined} isPending isError={false} onRetry={vi.fn()} activeId={null} onSelect={vi.fn()} onNew={vi.fn()} onRename={vi.fn()} onDelete={vi.fn()} />
    )
    expect(screen.getByLabelText("Loading conversations")).toBeInTheDocument()
    unmount()

    const retry = vi.fn()
    const errored = render(
      <ChatSessionSidebar sessions={undefined} isPending={false} isError onRetry={retry} activeId={null} onSelect={vi.fn()} onNew={vi.fn()} onRename={vi.fn()} onDelete={vi.fn()} />
    )
    await userEvent.setup().click(screen.getByRole("button", { name: "Try again" }))
    expect(retry).toHaveBeenCalledTimes(1)
    errored.unmount()

    render(
      <ChatSessionSidebar sessions={[]} isPending={false} isError={false} onRetry={vi.fn()} activeId={null} onSelect={vi.fn()} onNew={vi.fn()} onRename={vi.fn()} onDelete={vi.fn()} />
    )
    expect(screen.getByText("No conversations yet")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "New chat" })).toBeInTheDocument()
  })
})

describe("ChatSessionSidebar renaming", () => {
  async function startRename(user: ReturnType<typeof userEvent.setup>, title: string) {
    await user.click(screen.getByRole("button", { name: `Rename ${title}` }))
    return screen.getByRole("textbox", { name: `Rename ${title}` })
  }

  it("turns the title into an input pre-filled with the current title", async () => {
    setup()
    const input = await startRename(userEvent.setup(), "Overdue service report")
    expect(input).toHaveValue("Overdue service report")
    expect(input).toHaveFocus()
    // Only the row being edited swaps to an input.
    expect(screen.getByRole("button", { name: /^Fuel costs this month/ })).toBeInTheDocument()
  })

  it("saves the new title on Enter, once", async () => {
    const user = userEvent.setup()
    const props = setup()
    const input = await startRename(user, "Overdue service report")

    await user.clear(input)
    await user.type(input, "  Service backlog  {Enter}")

    expect(props.onRename).toHaveBeenCalledTimes(1)
    expect(props.onRename).toHaveBeenCalledWith("s1", "Service backlog")
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument()
  })

  it("cancels on Escape without saving", async () => {
    const user = userEvent.setup()
    const props = setup()
    const input = await startRename(user, "Overdue service report")

    await user.clear(input)
    await user.type(input, "Something else{Escape}")

    expect(props.onRename).not.toHaveBeenCalled()
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument()
    expect(screen.getByText("Overdue service report")).toBeInTheDocument()
  })

  it("does not call rename for an empty or unchanged title", async () => {
    const user = userEvent.setup()
    const props = setup()

    const first = await startRename(user, "Overdue service report")
    await user.clear(first)
    await user.type(first, "   {Enter}")

    const second = await startRename(user, "Overdue service report")
    await user.type(second, "{Enter}")

    expect(props.onRename).not.toHaveBeenCalled()
  })

  it("saves when the field loses focus", async () => {
    const user = userEvent.setup()
    const props = setup()
    const input = await startRename(user, "Fuel costs this month")

    await user.clear(input)
    await user.type(input, "Fuel review")
    await user.click(screen.getByRole("button", { name: "New chat" }))

    expect(props.onRename).toHaveBeenCalledWith("s2", "Fuel review")
    expect(props.onRename).toHaveBeenCalledTimes(1)
  })

  it("does not select the conversation while it is being renamed", async () => {
    const user = userEvent.setup()
    const props = setup()
    await startRename(user, "Overdue service report")
    expect(within(screen.getByRole("navigation", { name: "Chat history" })).queryByRole("button", { name: /^Overdue service report/ })).not.toBeInTheDocument()
    expect(props.onSelect).not.toHaveBeenCalled()
  })
})

describe("ChatSessionSidebar delete", () => {
  it("each conversation has a delete button beside rename that asks the page to delete it", async () => {
    const props = setup()
    const row = screen.getByRole("button", { name: "Delete Fuel costs this month" })
    expect(screen.getByRole("button", { name: "Rename Fuel costs this month" })).toBeInTheDocument()

    await userEvent.setup().click(row)

    expect(props.onDelete).toHaveBeenCalledWith("s2")
    expect(props.onSelect).not.toHaveBeenCalled() // the delete click doesn't also open it
  })
})
