import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import ChatPage from "@/app/(app)/chat/page"
import { TopbarSlotsProvider } from "@/components/layout/topbar-slots"
import { TooltipProvider } from "@/components/ui/tooltip"
import type { ChatEvent } from "@/lib/api/chat"

let currentParams = new URLSearchParams()
const mockPush = vi.fn()
const mockReplace = vi.fn()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
  useSearchParams: () => currentParams,
}))

const mockSessions = vi.fn()
const mockRename = vi.fn()
const mockCreate = vi.fn()
const mockGetMessages = vi.fn()
const mockSend = vi.fn()
vi.mock("@/lib/api/chat", () => ({
  useChatSessions: () => mockSessions(),
  useRenameChatSession: () => ({ mutate: mockRename }),
  createChatSession: () => mockCreate(),
  getChatMessages: (id: string) => mockGetMessages(id),
  sendChatMessage: (...args: unknown[]) => mockSend(...args),
  approveChatAction: vi.fn(),
  modifyChatAction: vi.fn(),
  rejectChatAction: vi.fn(),
}))

const SESSIONS = [
  { id: "s1", title: "Overdue service report", message_count: 2, created_at: "2026-09-30T08:00:00Z", updated_at: "2026-09-30T09:00:00Z" },
  { id: "s2", title: "Fuel costs this month", message_count: 2, created_at: "2026-09-29T08:00:00Z", updated_at: "2026-09-29T09:00:00Z" },
]

function sessionsState(data: unknown = SESSIONS) {
  return { data, isPending: false, isError: false, refetch: vi.fn() }
}

async function* reply(text: string): AsyncGenerator<ChatEvent> {
  yield { type: "token", text }
  yield { type: "done", status: "done" }
}

function stored(id: string, role: "user" | "assistant", content: string) {
  return { id, role, content, created_at: "2026-09-30T08:00:00Z" }
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const ui = () => (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <TopbarSlotsProvider>
          <ChatPage />
        </TopbarSlotsProvider>
      </TooltipProvider>
    </QueryClientProvider>
  )
  const utils = render(ui())
  return { ...utils, client, rerenderPage: () => utils.rerender(ui()) }
}

// The desktop sidebar and the composer are what a user drives; scope queries to them.
function sidebar() {
  return within(screen.getByRole("complementary", { name: "Conversations" }))
}

async function send(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(screen.getByPlaceholderText("Ask something…"), text)
  await user.click(screen.getByRole("button", { name: "Send" }))
}

describe("ChatPage", () => {
  beforeEach(() => {
    currentParams = new URLSearchParams()
    mockPush.mockReset()
    mockReplace.mockReset()
    mockRename.mockReset()
    mockCreate.mockReset().mockResolvedValue("new-session")
    mockGetMessages.mockReset().mockResolvedValue([])
    mockSend.mockReset().mockImplementation(() => reply("Here you go"))
    mockSessions.mockReturnValue(sessionsState())
  })

  it("lays the page out as a sidebar of past chats beside the active chat", () => {
    renderPage()
    expect(screen.getByRole("complementary", { name: "Conversations" })).toBeInTheDocument()
    expect(screen.getByRole("region", { name: "Chat" })).toBeInTheDocument()
    expect(sidebar().getByText("Overdue service report")).toBeInTheDocument()
    expect(sidebar().getByText("Fuel costs this month")).toBeInTheDocument()
    expect(sidebar().getByRole("button", { name: "New chat" })).toBeInTheDocument()
  })

  it("starts with an empty new-chat state and no stored history to fetch", () => {
    renderPage()
    expect(screen.getByText("Start a new conversation")).toBeInTheDocument()
    expect(mockGetMessages).not.toHaveBeenCalled()
  })

  describe("switching sessions", () => {
    it("clicking a session navigates to ?session={id}", async () => {
      renderPage()
      await userEvent.setup().click(sidebar().getByRole("button", { name: /^Fuel costs this month/ }))
      expect(mockPush).toHaveBeenCalledWith("/chat?session=s2")
    })

    it("opening ?session={id} fetches and renders that conversation's history and highlights it", async () => {
      currentParams = new URLSearchParams("session=s1")
      mockGetMessages.mockResolvedValue([stored("m1", "user", "Which vehicles are overdue?"), stored("m2", "assistant", "GH-3456 is overdue.")])

      renderPage()

      expect(await screen.findByText("Which vehicles are overdue?")).toBeInTheDocument()
      expect(screen.getByText("GH-3456 is overdue.")).toBeInTheDocument()
      expect(mockGetMessages).toHaveBeenCalledWith("s1")
      expect(sidebar().getByRole("button", { name: /^Overdue service report/ })).toHaveAttribute("aria-current", "true")
      expect(sidebar().getByRole("button", { name: /^Fuel costs this month/ })).not.toHaveAttribute("aria-current")
    })

    it("shows a loading state while history loads and blocks sending until it has", async () => {
      currentParams = new URLSearchParams("session=s1")
      let resolve!: (rows: unknown[]) => void
      mockGetMessages.mockReturnValue(new Promise((r) => (resolve = r)))

      renderPage()

      expect(await screen.findByRole("status", { name: "Loading conversation" })).toBeInTheDocument()
      expect(screen.getByPlaceholderText("Waiting…")).toBeDisabled()

      resolve([stored("m1", "user", "hello")])
      expect(await screen.findByText("hello")).toBeInTheDocument()
      expect(screen.getByPlaceholderText("Ask something…")).toBeEnabled()
    })

    it("replaces the conversation shown when the URL moves to a different session", async () => {
      currentParams = new URLSearchParams("session=s1")
      mockGetMessages.mockImplementation(async (id: string) => [stored(`${id}-m`, "user", id === "s1" ? "first chat message" : "second chat message")])
      const { rerenderPage } = renderPage()
      expect(await screen.findByText("first chat message")).toBeInTheDocument()

      currentParams = new URLSearchParams("session=s2")
      rerenderPage()

      expect(await screen.findByText("second chat message")).toBeInTheDocument()
      expect(screen.queryByText("first chat message")).not.toBeInTheDocument()
    })

    it("says so, and offers a fresh start, when the conversation cannot be loaded", async () => {
      currentParams = new URLSearchParams("session=gone")
      mockGetMessages.mockRejectedValue({ kind: "not_found", status: 404, message: "Unknown or expired chat session." })

      renderPage()

      const alert = await screen.findByRole("alert")
      expect(alert).toHaveTextContent("That conversation couldn't be found.")
      await userEvent.setup().click(within(alert).getByRole("button", { name: "Start a new chat" }))
      expect(mockPush).toHaveBeenCalledWith("/chat")
    })
  })

  describe("new chat", () => {
    it("clears the open conversation and removes ?session from the URL", async () => {
      const user = userEvent.setup()
      currentParams = new URLSearchParams("session=s1")
      mockGetMessages.mockResolvedValue([stored("m1", "user", "An old question")])
      renderPage()
      expect(await screen.findByText("An old question")).toBeInTheDocument()

      await user.click(sidebar().getByRole("button", { name: "New chat" }))

      expect(mockPush).toHaveBeenCalledWith("/chat")
      expect(screen.queryByText("An old question")).not.toBeInTheDocument()
      expect(screen.getByText("Start a new conversation")).toBeInTheDocument()
    })

    it("the next message starts a brand-new session rather than continuing the old one", async () => {
      const user = userEvent.setup()
      currentParams = new URLSearchParams("session=s1")
      renderPage()
      await waitFor(() => expect(mockGetMessages).toHaveBeenCalled())
      await user.click(sidebar().getByRole("button", { name: "New chat" }))

      await send(user, "a fresh question")

      await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1))
      expect(mockSend).toHaveBeenCalledWith("new-session", "a fresh question", expect.anything())
      expect(mockSend).not.toHaveBeenCalledWith("s1", expect.anything(), expect.anything())
    })
  })

  describe("sending messages", () => {
    it("in a new chat, creates the session first, puts it in the URL, then sends with that explicit id", async () => {
      const user = userEvent.setup()
      renderPage()

      await send(user, "Which vehicles are overdue?")

      await waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/chat?session=new-session"))
      expect(mockCreate).toHaveBeenCalledTimes(1)
      expect(mockSend).toHaveBeenCalledWith("new-session", "Which vehicles are overdue?", expect.anything())
      expect(await screen.findByText("Here you go")).toBeInTheDocument()
    })

    it("in an opened conversation, appends to that session and creates no new one", async () => {
      const user = userEvent.setup()
      currentParams = new URLSearchParams("session=s1")
      mockGetMessages.mockResolvedValue([stored("m1", "user", "earlier")])
      renderPage()
      await screen.findByText("earlier")

      await send(user, "a follow up")

      await waitFor(() => expect(mockSend).toHaveBeenCalledWith("s1", "a follow up", expect.anything()))
      expect(mockCreate).not.toHaveBeenCalled()
      expect(mockReplace).not.toHaveBeenCalled()
    })

    it("keeps using the same session for a second message in a new chat", async () => {
      const user = userEvent.setup()
      renderPage()

      await send(user, "first")
      await screen.findByText("Here you go")
      await send(user, "second")

      await waitFor(() => expect(mockSend).toHaveBeenCalledTimes(2))
      expect(mockCreate).toHaveBeenCalledTimes(1)
      expect(mockSend.mock.calls.map((c) => c[0])).toEqual(["new-session", "new-session"])
    })

    it("if creating the session fails, shows the error and does not leave a phantom message", async () => {
      const user = userEvent.setup()
      mockCreate.mockRejectedValue({ kind: "unavailable", status: 503, message: "The memory service is unavailable." })
      renderPage()

      await send(user, "hello?")

      expect(await screen.findByRole("alert")).toHaveTextContent("The memory service is unavailable.")
      expect(screen.queryByText("hello?")).not.toBeInTheDocument()
      expect(mockSend).not.toHaveBeenCalled()
      expect(mockReplace).not.toHaveBeenCalled()
    })

    it("re-reads the session list once a reply has landed, so the new title and ordering appear", async () => {
      const user = userEvent.setup()
      const { client } = renderPage()
      const invalidate = vi.spyOn(client, "invalidateQueries")

      await send(user, "hi")
      await screen.findByText("Here you go")

      await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["chat", "sessions"] }))
    })

    it("does not re-read the list while the reply is still streaming", async () => {
      const user = userEvent.setup()
      let release!: () => void
      const gate = new Promise<void>((r) => (release = r))
      mockSend.mockImplementation(async function* () {
        yield { type: "token", text: "partial" } as ChatEvent
        await gate
        yield { type: "done", status: "done" } as ChatEvent
      })
      const { client } = renderPage()
      const invalidate = vi.spyOn(client, "invalidateQueries")

      await send(user, "hi")
      await screen.findByText("partial")
      expect(invalidate).not.toHaveBeenCalled()

      release()
      await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["chat", "sessions"] }))
    })
  })

  describe("renaming", () => {
    it("renames from the sidebar via the edit control", async () => {
      const user = userEvent.setup()
      renderPage()

      await user.click(sidebar().getByRole("button", { name: "Rename Overdue service report" }))
      const input = sidebar().getByRole("textbox", { name: "Rename Overdue service report" })
      await user.clear(input)
      await user.type(input, "Service backlog{Enter}")

      expect(mockRename).toHaveBeenCalledWith({ id: "s1", title: "Service backlog" }, expect.any(Object))
    })
  })

  describe("mobile drawer", () => {
    it("hides the list behind a Chats toggle, and closes it after choosing", async () => {
      const user = userEvent.setup()
      renderPage()
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()

      await user.click(screen.getByRole("button", { name: "Chats" }))
      const drawer = await screen.findByRole("dialog", { name: "Conversations" })
      await user.click(within(drawer).getByRole("button", { name: /^Fuel costs this month/ }))

      expect(mockPush).toHaveBeenCalledWith("/chat?session=s2")
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    })
  })
})
