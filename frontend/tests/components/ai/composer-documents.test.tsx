import { fireEvent, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { Composer, type MentionableDocument } from "@/components/ai/composer"

const MANUAL: MentionableDocument = { id: "doc-1", filename: "Fleet Operations Manual.pdf", document_type: "manual" }
const POLICY: MentionableDocument = { id: "doc-2", filename: "Fuel Card Policy.pdf", document_type: "policy" }
const INVOICE: MentionableDocument = { id: "doc-3", filename: "Supplier Invoice 4471.pdf", document_type: "supplier_invoice" }
const DOCS = [MANUAL, POLICY, INVOICE]

const PLACEHOLDER = "Ask something… (type @ to reference a document)"

function setup(props: Partial<React.ComponentProps<typeof Composer>> = {}) {
  const onSend = vi.fn()
  const user = userEvent.setup()
  render(<Composer onSend={onSend} documents={DOCS} {...props} />)
  return { onSend, user, textarea: () => screen.getByPlaceholderText(PLACEHOLDER) as HTMLTextAreaElement }
}

describe("Composer @ mentions", () => {
  it("opens a list of the library's documents when @ is typed, and says how to use it", async () => {
    const { user, textarea } = setup()

    await user.type(textarea(), "What does @")

    const list = screen.getByRole("listbox", { name: "Documents to reference" })
    expect(within(list).getAllByRole("option").map((o) => o.textContent)).toEqual([
      expect.stringContaining("Fleet Operations Manual.pdf"),
      expect.stringContaining("Fuel Card Policy.pdf"),
      expect.stringContaining("Supplier Invoice 4471.pdf"),
    ])
    expect(within(list).getByText("Manual")).toBeInTheDocument() // the type badge
  })

  it("filters as the user keeps typing", async () => {
    const { user, textarea } = setup()

    await user.type(textarea(), "@fuel")

    expect(screen.getAllByRole("option")).toHaveLength(1)
    expect(screen.getByRole("option")).toHaveTextContent("Fuel Card Policy.pdf")

    await user.type(textarea(), "zzz")
    expect(screen.queryByRole("option")).not.toBeInTheDocument()
    expect(screen.getByText("No matching documents.")).toBeInTheDocument()
  })

  it("tells a user with an empty library there is nothing to reference yet", async () => {
    const { user, textarea } = setup({ documents: [] })

    await user.type(textarea(), "@")

    expect(screen.getByText("No documents in your library yet.")).toBeInTheDocument()
  })

  it("does nothing for an @ in the middle of a word (an e-mail address) or when mentions are off", async () => {
    const { user, textarea } = setup()
    await user.type(textarea(), "mail me at jo@")
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()

    const off = render(<Composer onSend={vi.fn()} />)
    await user.type(within(off.container).getByPlaceholderText("Ask something…"), "@")
    expect(within(off.container).queryByRole("listbox")).not.toBeInTheDocument()
  })

  it("inserts the chosen document's name into the text and shows a removable pill", async () => {
    const { user, textarea } = setup()

    await user.type(textarea(), "What does @fuel")
    await user.click(screen.getByRole("option", { name: /Fuel Card Policy\.pdf/ }))

    expect(textarea()).toHaveValue("What does @Fuel Card Policy.pdf ")
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
    expect(within(screen.getByRole("list", { name: "Referenced documents" })).getByText("@Fuel Card Policy.pdf")).toBeInTheDocument()
    expect(textarea()).toHaveFocus()
    expect(textarea().selectionStart).toBe("What does @Fuel Card Policy.pdf ".length) // the caret is past the name, ready to keep typing
  })

  it("selects with the keyboard: arrows move, Enter chooses, and Enter then does not send", async () => {
    const { onSend, user, textarea } = setup()

    await user.type(textarea(), "@")
    fireEvent.keyDown(textarea(), { key: "ArrowDown" })
    expect(screen.getAllByRole("option")[1]).toHaveAttribute("aria-selected", "true")
    fireEvent.keyDown(textarea(), { key: "ArrowUp" })
    fireEvent.keyDown(textarea(), { key: "ArrowUp" }) // wraps to the last
    expect(screen.getAllByRole("option")[2]).toHaveAttribute("aria-selected", "true")
    fireEvent.keyDown(textarea(), { key: "Enter" })

    expect(textarea()).toHaveValue("@Supplier Invoice 4471.pdf ")
    expect(onSend).not.toHaveBeenCalled()
    expect(screen.getByTestId("mention-pill")).toHaveTextContent("@Supplier Invoice 4471.pdf")
  })

  it("Tab also chooses, and Escape closes the list without choosing", async () => {
    const { user, textarea } = setup()

    await user.type(textarea(), "@")
    fireEvent.keyDown(textarea(), { key: "Escape" })
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
    expect(screen.queryByTestId("mention-pill")).not.toBeInTheDocument()

    await user.clear(textarea())
    await user.type(textarea(), "@")
    fireEvent.keyDown(textarea(), { key: "Tab" })
    expect(screen.getByTestId("mention-pill")).toHaveTextContent("@Fleet Operations Manual.pdf")
  })

  it("Enter still sends when the list has nothing to choose", async () => {
    const { onSend, user, textarea } = setup()

    await user.type(textarea(), "@nothing matches")
    fireEvent.keyDown(textarea(), { key: "Enter" })

    expect(onSend).toHaveBeenCalledWith("@nothing matches", null)
  })

  it("removing a pill takes its name out of the text too", async () => {
    const { user, textarea } = setup()
    await user.type(textarea(), "@")
    await user.click(screen.getByRole("option", { name: /Fleet Operations Manual/ }))
    await user.type(textarea(), "and the tyre section")
    expect(textarea()).toHaveValue("@Fleet Operations Manual.pdf and the tyre section")

    await user.click(screen.getByRole("button", { name: "Remove @Fleet Operations Manual.pdf" }))

    expect(screen.queryByTestId("mention-pill")).not.toBeInTheDocument()
    expect(textarea()).toHaveValue("and the tyre section")
  })

  it("does not offer a document that is already referenced", async () => {
    const { user, textarea } = setup()
    await user.type(textarea(), "@")
    await user.click(screen.getByRole("option", { name: /Fleet Operations Manual/ }))

    await user.type(textarea(), "@")

    expect(screen.getAllByRole("option").map((o) => o.textContent)).not.toContain(expect.stringContaining("Fleet Operations Manual"))
    expect(screen.getAllByRole("option")).toHaveLength(2)
  })

  it("sends the referenced documents with the text, then clears the pills", async () => {
    const { onSend, user, textarea } = setup()
    await user.type(textarea(), "@")
    await user.click(screen.getByRole("option", { name: /Fuel Card Policy/ }))
    await user.type(textarea(), "what is the limit?")

    await user.click(screen.getByRole("button", { name: "Send" }))

    expect(onSend).toHaveBeenCalledWith("@Fuel Card Policy.pdf what is the limit?", null, { pdf: null, documents: [POLICY] })
    expect(screen.queryByTestId("mention-pill")).not.toBeInTheDocument()
    expect(textarea()).toHaveValue("")
  })

  it("keeps the pills and text when the send fails", async () => {
    const { user, textarea } = setup({ onSend: () => Promise.resolve(false) })
    await user.type(textarea(), "@")
    await user.click(screen.getByRole("option", { name: /Fuel Card Policy/ }))

    await user.click(screen.getByRole("button", { name: "Send" }))

    expect(screen.getByTestId("mention-pill")).toBeInTheDocument()
    expect(textarea()).toHaveValue("@Fuel Card Policy.pdf ")
  })

  it("only offers the list while the caret is on the mention being typed", async () => {
    const { user, textarea } = setup()
    await user.type(textarea(), "@fu")
    expect(screen.getByRole("listbox")).toBeInTheDocument()

    await user.type(textarea(), " and then")

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
  })
})

describe("Composer PDF attachments", () => {
  const pdf = (name = "driver-handbook.pdf", size = 2048) => new File([new Uint8Array(size)], name, { type: "application/pdf" })

  it("accepts a PDF beside images when the user may upload documents", () => {
    render(<Composer onSend={vi.fn()} pdfTypes={["manual", "policy"]} />)

    expect(screen.getByTestId("composer-image-input")).toHaveAttribute("accept", "image/jpeg, image/png, image/webp, application/pdf")
    expect(screen.getByRole("button", { name: "Attach an image or PDF" })).toBeInTheDocument()
  })

  it("stages a PDF as a chip with its name, size and a document-type choice, and the X removes it", async () => {
    const user = userEvent.setup()
    render(<Composer onSend={vi.fn()} pdfTypes={["manual", "policy"]} />)

    await user.upload(screen.getByTestId("composer-image-input"), pdf("driver-handbook.pdf", 2048))

    const chip = screen.getByTestId("pdf-chip")
    expect(chip).toHaveTextContent("driver-handbook.pdf")
    expect(chip).toHaveTextContent("2 KB")
    expect(within(chip).getByRole("combobox", { name: "Document type" })).toHaveTextContent("Manual")
    expect(screen.getByPlaceholderText("Ask about this document (optional)…")).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Remove attached PDF" }))
    expect(screen.queryByTestId("pdf-chip")).not.toBeInTheDocument()
  })

  it("lets a PDF go out on its own, with the chosen type", async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()
    render(<Composer onSend={onSend} pdfTypes={["manual", "policy"]} />)
    const send = screen.getByRole("button", { name: "Send" })
    expect(send).toBeDisabled()

    const file = pdf()
    await user.upload(screen.getByTestId("composer-image-input"), file)
    expect(send).toBeEnabled()
    await user.click(send)

    expect(onSend).toHaveBeenCalledWith("", null, { pdf: { file, documentType: "manual" }, documents: [] })
  })

  it("does not ask for a type when only one is allowed", async () => {
    const user = userEvent.setup()
    render(<Composer onSend={vi.fn()} pdfTypes={["manual"]} />)

    await user.upload(screen.getByTestId("composer-image-input"), pdf())

    expect(screen.queryByRole("combobox", { name: "Document type" })).not.toBeInTheDocument()
  })

  it("a PDF and a photo replace each other: only one attachment at a time", async () => {
    URL.createObjectURL = vi.fn(() => "blob:preview")
    URL.revokeObjectURL = vi.fn()
    const user = userEvent.setup()
    render(<Composer onSend={vi.fn()} pdfTypes={["manual"]} />)
    const input = screen.getByTestId("composer-image-input")

    await user.upload(input, new File(["x"], "receipt.png", { type: "image/png" }))
    await user.upload(input, pdf())
    expect(screen.queryByAltText("Attached: receipt.png")).not.toBeInTheDocument()
    expect(screen.getByTestId("pdf-chip")).toBeInTheDocument()

    await user.upload(input, new File(["x"], "receipt.png", { type: "image/png" }))
    expect(screen.queryByTestId("pdf-chip")).not.toBeInTheDocument()
    expect(screen.getByAltText("Attached: receipt.png")).toBeInTheDocument()
  })

  it("refuses an oversized PDF", () => {
    render(<Composer onSend={vi.fn()} pdfTypes={["manual"]} />)

    fireEvent.change(screen.getByTestId("composer-image-input"), {
      target: { files: [new File([new Uint8Array(20 * 1024 * 1024 + 1)], "huge.pdf", { type: "application/pdf" })] },
    })

    expect(screen.getByRole("alert")).toHaveTextContent("PDFs must be 20 MB or smaller.")
    expect(screen.queryByTestId("pdf-chip")).not.toBeInTheDocument()
  })

  it("names the real options when something else is attached", () => {
    render(<Composer onSend={vi.fn()} pdfTypes={["manual"]} />)

    fireEvent.change(screen.getByTestId("composer-image-input"), { target: { files: [new File(["x"], "notes.docx", { type: "application/msword" })] } })

    expect(screen.getByRole("alert")).toHaveTextContent("Only JPEG, PNG or WebP images, or PDFs, can be attached.")
  })

  it("a user who may not upload documents cannot stage a PDF", () => {
    render(<Composer onSend={vi.fn()} pdfTypes={[]} />)

    expect(screen.getByTestId("composer-image-input")).toHaveAttribute("accept", "image/jpeg, image/png, image/webp")
    fireEvent.change(screen.getByTestId("composer-image-input"), { target: { files: [pdf()] } })

    expect(screen.getByRole("alert")).toHaveTextContent("Only JPEG, PNG or WebP images can be attached.")
    expect(screen.queryByTestId("pdf-chip")).not.toBeInTheDocument()
  })

  it("sends a PDF together with mentions and the typed question", async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()
    render(<Composer onSend={onSend} documents={DOCS} pdfTypes={["manual"]} />)
    const textarea = screen.getByPlaceholderText(PLACEHOLDER)
    await user.type(textarea, "@")
    await user.click(screen.getByRole("option", { name: /Fuel Card Policy/ }))
    const file = pdf()
    await user.upload(screen.getByTestId("composer-image-input"), file)
    await user.type(screen.getByPlaceholderText("Ask about this document (optional)…"), "compare them")

    await user.click(screen.getByRole("button", { name: "Send" }))

    expect(onSend).toHaveBeenCalledWith("@Fuel Card Policy.pdf compare them", null, { pdf: { file, documentType: "manual" }, documents: [POLICY] })
  })
})
