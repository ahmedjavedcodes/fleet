import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import ChatPage from "@/app/(app)/chat/page"
import { TopbarSlotsProvider } from "@/components/layout/topbar-slots"
import { TooltipProvider } from "@/components/ui/tooltip"
import type { ChatEvent } from "@/lib/api/chat"

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))

const mockCreate = vi.fn()
const mockSend = vi.fn()
vi.mock("@/lib/api/chat", () => ({
  useChatSessions: () => ({ data: [], isPending: false, isError: false, refetch: vi.fn() }),
  useRenameChatSession: () => ({ mutate: vi.fn() }),
  useDeleteChatSession: () => ({ mutate: vi.fn() }),
  createChatSession: () => mockCreate(),
  getChatMessages: vi.fn().mockResolvedValue([]),
  sendChatMessage: (...args: unknown[]) => mockSend(...args),
  approveChatAction: vi.fn(),
  modifyChatAction: vi.fn(),
  rejectChatAction: vi.fn(),
}))
vi.mock("@/lib/api/uploads", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/uploads")>()),
  uploadImage: vi.fn(),
}))

const mockDocuments = vi.fn()
const mockUploadDocument = vi.fn()
const mockWaitReady = vi.fn()
vi.mock("@/lib/api/documents", () => ({
  useDocuments: (options: unknown) => mockDocuments(options),
  uploadDocument: (input: unknown) => mockUploadDocument(input),
  waitForDocumentReady: (...args: unknown[]) => mockWaitReady(...args),
}))

const mockUser = vi.fn()
vi.mock("@/lib/auth/use-current-user", () => ({ useCurrentUser: () => mockUser() }))

function doc(id: string, filename: string, status = "ready", document_type = "manual") {
  return { id, filename, document_type, status, vehicle_id: null, version: 1, size_bytes: 10, chunk_count: 4, tables_found: 0, tables_summarized: 0, error_message: null, created_at: "", updated_at: "" }
}
type DocRecord = ReturnType<typeof doc>
const MANUAL = doc("doc-1", "Fleet Manual.pdf")
const POLICY = doc("doc-2", "Fuel Policy.pdf", "ready", "policy")
const PROCESSING = doc("doc-3", "Half Done.pdf", "processing")

async function* reply(text: string): AsyncGenerator<ChatEvent> {
  yield { type: "token", text }
  yield { type: "done", status: "done" }
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <TopbarSlotsProvider>
          <ChatPage />
        </TopbarSlotsProvider>
      </TooltipProvider>
    </QueryClientProvider>
  )
}

const PLACEHOLDER = "Ask something… (type @ to reference a document)"

describe("ChatPage documents", () => {
  beforeEach(() => {
    mockCreate.mockReset().mockResolvedValue("new-session")
    mockSend.mockReset().mockImplementation(() => reply("One hour."))
    mockUploadDocument.mockReset()
    mockWaitReady.mockReset()
    mockUser.mockReturnValue({ role: "fleet_manager" })
    mockDocuments.mockReset().mockReturnValue({ data: [MANUAL, POLICY, PROCESSING] })
  })

  describe("@ mentions", () => {
    it("lists only the ready documents and only asks for them when the role may search documents", async () => {
      const user = userEvent.setup()
      renderPage()

      expect(mockDocuments).toHaveBeenCalledWith({ enabled: true })
      await user.type(screen.getByPlaceholderText(PLACEHOLDER), "@")

      expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual([
        expect.stringContaining("Fleet Manual.pdf"),
        expect.stringContaining("Fuel Policy.pdf"),
      ]) // "Half Done.pdf" is still processing, so it can't be searched yet
    })

    it("sends the chosen documents' ids with the message and shows them under it", async () => {
      const user = userEvent.setup()
      renderPage()

      await user.type(screen.getByPlaceholderText(PLACEHOLDER), "How fast must an accident be reported per @fleet")
      await user.click(screen.getByRole("option", { name: /Fleet Manual\.pdf/ }))
      await user.click(screen.getByRole("button", { name: "Send" }))

      await waitFor(() => expect(mockSend).toHaveBeenCalledTimes(1))
      expect(mockSend).toHaveBeenCalledWith(
        "new-session",
        "How fast must an accident be reported per @Fleet Manual.pdf",
        expect.anything(),
        undefined,
        ["doc-1"]
      )
      const chips = await screen.findByRole("list", { name: "Referenced documents" })
      expect(within(chips).getByText("Fleet Manual.pdf")).toBeInTheDocument()
      expect(await screen.findByText("One hour.")).toBeInTheDocument()
    })

    it("a message without mentions is sent exactly as before", async () => {
      const user = userEvent.setup()
      renderPage()

      await user.type(screen.getByPlaceholderText(PLACEHOLDER), "How many vehicles do we have?")
      await user.click(screen.getByRole("button", { name: "Send" }))

      await waitFor(() => expect(mockSend).toHaveBeenCalledWith("new-session", "How many vehicles do we have?", expect.anything(), undefined))
    })

    it("does not offer mentions at all to a role that cannot search documents", () => {
      mockUser.mockReturnValue({ role: null })
      renderPage()

      expect(mockDocuments).toHaveBeenCalledWith({ enabled: false })
      expect(screen.getByPlaceholderText("Ask something…")).toBeInTheDocument()
    })
  })

  describe("PDF attachments", () => {
    const pdf = new File([new Uint8Array(2048)], "driver-handbook.pdf", { type: "application/pdf" })

    it("uploads the PDF, waits until it has been processed, then sends the question restricted to it", async () => {
      let finish: (document: DocRecord) => void = () => {}
      mockUploadDocument.mockResolvedValue(doc("doc-9", "driver-handbook.pdf", "processing"))
      mockWaitReady.mockImplementation(() => new Promise((resolve) => (finish = resolve)))
      const user = userEvent.setup()
      renderPage()

      await user.upload(screen.getByTestId("composer-image-input"), pdf)
      await user.type(screen.getByPlaceholderText("Ask about this document (optional)…"), "What are the shift rules?")
      await user.click(screen.getByRole("button", { name: "Send" }))

      await waitFor(() => expect(mockUploadDocument).toHaveBeenCalledWith({ file: pdf, document_type: "manual" }))
      expect(await screen.findByText("driver-handbook.pdf", { selector: "p" })).toBeInTheDocument() // the progress card, while it processes
      expect(mockSend).not.toHaveBeenCalled() // nothing is asked of a document that is not ready
      expect(mockCreate).not.toHaveBeenCalled()

      finish(doc("doc-9", "driver-handbook.pdf", "ready"))

      await waitFor(() => expect(mockSend).toHaveBeenCalledTimes(1))
      expect(mockWaitReady).toHaveBeenCalledWith("doc-9", expect.objectContaining({ signal: expect.any(AbortSignal) }))
      expect(mockSend).toHaveBeenCalledWith("new-session", "What are the shift rules? @driver-handbook.pdf", expect.anything(), undefined, ["doc-9"])
      expect(screen.queryByText("driver-handbook.pdf", { selector: "p" })).not.toBeInTheDocument() // the card is gone once it is ready
    })

    it("a PDF sent with no text is asked to be summarised", async () => {
      mockUploadDocument.mockResolvedValue(doc("doc-9", "driver-handbook.pdf", "processing"))
      mockWaitReady.mockResolvedValue(doc("doc-9", "driver-handbook.pdf", "ready"))
      const user = userEvent.setup()
      renderPage()

      await user.upload(screen.getByTestId("composer-image-input"), pdf)
      await user.click(screen.getByRole("button", { name: "Send" }))

      await waitFor(() =>
        expect(mockSend).toHaveBeenCalledWith("new-session", "Summarize this document. @driver-handbook.pdf", expect.anything(), undefined, ["doc-9"])
      )
    })

    it("combines an attached PDF with a mentioned document", async () => {
      mockUploadDocument.mockResolvedValue(doc("doc-9", "driver-handbook.pdf", "processing"))
      mockWaitReady.mockResolvedValue(doc("doc-9", "driver-handbook.pdf", "ready"))
      const user = userEvent.setup()
      renderPage()
      await user.type(screen.getByPlaceholderText(PLACEHOLDER), "@fuel")
      await user.click(screen.getByRole("option", { name: /Fuel Policy/ }))
      await user.upload(screen.getByTestId("composer-image-input"), pdf)
      await user.type(screen.getByPlaceholderText("Ask about this document (optional)…"), "do they agree?")
      await user.click(screen.getByRole("button", { name: "Send" }))

      await waitFor(() => expect(mockSend).toHaveBeenCalledTimes(1))
      expect(mockSend.mock.calls[0]![4]).toEqual(["doc-2", "doc-9"])
    })

    it("reports a PDF that could not be processed, sends nothing, and keeps the attachment to retry", async () => {
      mockUploadDocument.mockResolvedValue(doc("doc-9", "driver-handbook.pdf", "processing"))
      mockWaitReady.mockRejectedValue(new Error("no extractable text (scanned/image-only PDFs are not supported)"))
      const user = userEvent.setup()
      renderPage()
      await user.upload(screen.getByTestId("composer-image-input"), pdf)
      await user.click(screen.getByRole("button", { name: "Send" }))

      expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't add driver-handbook.pdf: no extractable text")
      expect(mockSend).not.toHaveBeenCalled()
      expect(mockCreate).not.toHaveBeenCalled()
      expect(screen.getByTestId("pdf-chip")).toBeInTheDocument() // still staged, so the user can retry or remove it
    })

    it("reports an upload the server rejected", async () => {
      mockUploadDocument.mockRejectedValue(new Error("Only PDF and plain-text documents are supported"))
      const user = userEvent.setup()
      renderPage()
      await user.upload(screen.getByTestId("composer-image-input"), pdf)
      await user.click(screen.getByRole("button", { name: "Send" }))

      expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't add driver-handbook.pdf: Only PDF and plain-text documents are supported")
      expect(mockWaitReady).not.toHaveBeenCalled()
    })

    it("does not let a role that cannot upload documents attach a PDF", async () => {
      mockUser.mockReturnValue({ role: "driver" })
      renderPage()

      expect(screen.getByTestId("composer-image-input")).toHaveAttribute("accept", "image/jpeg, image/png, image/webp")
      expect(screen.getByRole("button", { name: "Attach an image" })).toBeInTheDocument()
      // ...but can still mention the documents they may read
      await userEvent.setup().type(screen.getByPlaceholderText(PLACEHOLDER), "@")
      expect(screen.getAllByRole("option")).toHaveLength(2)
    })
  })
})
