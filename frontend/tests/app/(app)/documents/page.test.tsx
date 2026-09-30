import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import DocumentsPage from "@/app/(app)/documents/page"
import { renderWithProviders as render } from "../../../test-utils"

const mockUseCurrentUser = vi.fn()
vi.mock("@/lib/auth/use-current-user", () => ({ useCurrentUser: () => mockUseCurrentUser() }))

const mockDocuments = vi.fn()
const mockUpload = vi.fn()
const mockDelete = vi.fn()
const mockSearch = vi.fn()
const mockChunks = vi.fn()
vi.mock("@/lib/api/documents", () => ({
  useDocuments: () => mockDocuments(),
  useUploadDocument: () => mockUpload(),
  useDeleteDocument: () => mockDelete(),
  useSearchDocuments: () => mockSearch(),
  useDocumentChunks: (id: string, enabled: boolean) => mockChunks(id, enabled),
}))
vi.mock("@/lib/api/vehicles", () => ({
  useVehicles: () => ({ data: [{ id: "veh-1", plate_number: "AB-1234" }], isPending: false, error: null }),
}))

const READY_DOC = {
  id: "doc-1",
  filename: "hilux-manual.pdf",
  document_type: "manual",
  vehicle_id: "veh-1",
  status: "ready",
  version: 2,
  size_bytes: 4096,
  chunk_count: 12,
  tables_found: 1,
  tables_summarized: 1,
  error_message: null,
  created_at: "2026-09-30T08:00:00Z",
  updated_at: "2026-09-30T09:00:00Z",
}
const FAILED_DOC = { ...READY_DOC, id: "doc-2", version: 1, filename: "scan.pdf", vehicle_id: null, status: "failed", error_message: "No extractable text" }

function query<T>(data: T) {
  return { data, isPending: false, error: null, refetch: vi.fn() }
}
function idleMutation() {
  return { mutate: vi.fn(), isPending: false, isError: false, error: null, data: undefined }
}

describe("DocumentsPage", () => {
  beforeEach(() => {
    mockDocuments.mockReturnValue(query([READY_DOC, FAILED_DOC]))
    mockUpload.mockReturnValue(idleMutation())
    mockDelete.mockReturnValue(idleMutation())
    mockSearch.mockReturnValue(idleMutation())
  })

  it("renders the real library instead of the 'not available yet' placeholder", () => {
    mockUseCurrentUser.mockReturnValue({ role: "driver" })
    render(<DocumentsPage />)

    expect(screen.queryByText(/isn't available yet/)).not.toBeInTheDocument()
    const table = screen.getByRole("table")
    expect(within(table).getByText("hilux-manual.pdf")).toBeInTheDocument()
    expect(within(table).getByText("v2")).toBeInTheDocument()
  })

  it("shows the vehicle's plate number rather than its id, and a failed document's reason", () => {
    mockUseCurrentUser.mockReturnValue({ role: "driver" })
    render(<DocumentsPage />)

    expect(screen.getByText("AB-1234")).toBeInTheDocument()
    expect(screen.queryByText("veh-1")).not.toBeInTheDocument()
    expect(screen.getByText("No extractable text")).toBeInTheDocument()
  })

  it("shows an empty state when there are no documents", () => {
    mockUseCurrentUser.mockReturnValue({ role: "driver" })
    mockDocuments.mockReturnValue(query([]))
    render(<DocumentsPage />)

    expect(screen.getByText("No documents yet")).toBeInTheDocument()
    expect(screen.queryByRole("table")).not.toBeInTheDocument()
  })

  it("hides upload and delete from a driver but keeps search", () => {
    mockUseCurrentUser.mockReturnValue({ role: "driver" })
    render(<DocumentsPage />)

    expect(screen.queryByText("Upload a document")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument()
    expect(screen.getByRole("search")).toBeInTheDocument()
  })

  it("offers upload and delete to an admin", () => {
    mockUseCurrentUser.mockReturnValue({ role: "admin" })
    render(<DocumentsPage />)

    expect(screen.getByText("Upload a document")).toBeInTheDocument()
    expect(screen.getAllByRole("button", { name: "Delete" })).toHaveLength(2)
  })

  it("deletes a document only after the confirmation dialog is accepted", async () => {
    const user = userEvent.setup()
    const remove = idleMutation()
    mockDelete.mockReturnValue(remove)
    mockUseCurrentUser.mockReturnValue({ role: "fleet_manager" })
    render(<DocumentsPage />)

    await user.click(screen.getAllByRole("button", { name: "Delete" })[0]!)
    expect(remove.mutate).not.toHaveBeenCalled()

    const dialog = await screen.findByRole("alertdialog")
    await user.click(within(dialog).getByRole("button", { name: "Delete" }))
    expect(remove.mutate).toHaveBeenCalledWith("doc-1", expect.any(Object))
  })

  it("disables the upload button until a file is chosen", () => {
    mockUseCurrentUser.mockReturnValue({ role: "admin" })
    render(<DocumentsPage />)
    expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled()
  })

  it("won't search for fewer than 3 characters, then sends the trimmed query", async () => {
    const user = userEvent.setup()
    const search = idleMutation()
    mockSearch.mockReturnValue(search)
    mockUseCurrentUser.mockReturnValue({ role: "driver" })
    render(<DocumentsPage />)

    const box = screen.getByRole("textbox", { name: "Search documents" })
    await user.type(box, "ab")
    expect(screen.getByRole("button", { name: "Search" })).toBeDisabled()

    await user.type(box, "c  ")
    await user.click(screen.getByRole("button", { name: "Search" }))
    expect(search.mutate).toHaveBeenCalledWith({ query: "abc" })
  })

  it("lists search hits with a relevance percentage, and says so when nothing matched", () => {
    mockUseCurrentUser.mockReturnValue({ role: "driver" })
    mockSearch.mockReturnValue({
      ...idleMutation(),
      data: {
        cached: false,
        results: [
          { document_id: "doc-1", filename: "hilux-manual.pdf", document_type: "manual", chunk_index: 3, text: "Replace brake pads every 40,000 km.", relevance: 0.87 },
        ],
      },
    })
    const { unmount } = render(<DocumentsPage />)
    expect(screen.getByText("Replace brake pads every 40,000 km.")).toBeInTheDocument()
    expect(screen.getByText("87% match")).toBeInTheDocument()
    unmount()

    mockSearch.mockReturnValue({ ...idleMutation(), data: { cached: false, results: [] } })
    render(<DocumentsPage />)
    expect(screen.getByText("No matching passages")).toBeInTheDocument()
  })

  describe("document preview", () => {
    const CHUNKS = [
      { chunk_index: 2, text: "2.0 Incident Protocols\nIntro passage before the answer." },
      { chunk_index: 3, text: "2.0 Incident Protocols\nReplace brake pads every 40,000 km." },
    ]

    beforeEach(() => {
      Element.prototype.scrollIntoView = vi.fn()
      mockChunks.mockReset().mockReturnValue({ data: CHUNKS, isPending: false, isError: false })
    })

    it("opens a ready document's text from the library and closes again", async () => {
      mockUseCurrentUser.mockReturnValue({ role: "driver" })
      const user = userEvent.setup()
      render(<DocumentsPage />)

      await user.click(screen.getByRole("button", { name: "Preview hilux-manual.pdf" }))

      const region = screen.getByRole("region", { name: "Document text" })
      expect(within(region).getByRole("heading", { level: 3, name: "2.0 Incident Protocols" })).toBeInTheDocument()
      expect(mockChunks).toHaveBeenCalledWith("doc-1", true)
      expect(document.querySelector("mark")).toBeNull() // no search, so nothing highlighted

      await user.click(screen.getByRole("button", { name: "Close" }))
      expect(screen.queryByRole("region", { name: "Document text" })).not.toBeInTheDocument()
    })

    it("has no Preview for a document that failed to process", () => {
      mockUseCurrentUser.mockReturnValue({ role: "driver" })
      render(<DocumentsPage />)

      expect(screen.queryByRole("button", { name: "Preview scan.pdf" })).not.toBeInTheDocument()
    })

    it("opening a search hit shows the document with the matching passage and the search terms highlighted", async () => {
      mockUseCurrentUser.mockReturnValue({ role: "driver" })
      mockSearch.mockReturnValue({
        ...idleMutation(),
        data: {
          cached: false,
          results: [
            { document_id: "doc-1", filename: "hilux-manual.pdf", document_type: "manual", chunk_index: 3, text: "Replace brake pads every 40,000 km.", relevance: 0.87 },
          ],
        },
      })
      const user = userEvent.setup()
      render(<DocumentsPage />)
      await user.type(screen.getByRole("textbox", { name: "Search documents" }), "when are brake pads replaced")
      await user.click(screen.getByRole("button", { name: "Search" }))

      await user.click(screen.getAllByRole("button", { name: /hilux-manual\.pdf/ })[0]!)

      const region = screen.getByRole("region", { name: "Document text" })
      const passage = region.querySelector('[data-hit="true"]') as HTMLElement
      expect(passage).toHaveAttribute("data-chunk", "3")
      expect(passage).toHaveClass("bg-primary-soft")
      expect(Array.from(region.querySelectorAll("mark")).map((m) => m.textContent?.toLowerCase())).toContain("brake")
      expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
    })
  })
})
