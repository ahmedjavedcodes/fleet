import { render, screen, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { buildSections, DocumentPreviewSheet, splitChunk, trimOverlap } from "@/components/ai/document-preview"
import { highlightTerms } from "@/components/ai/highlight"
import type { DocumentChunk } from "@/lib/schemas/document"

const mockChunks = vi.fn()
vi.mock("@/lib/api/documents", () => ({ useDocumentChunks: (id: string, enabled: boolean) => mockChunks(id, enabled) }))

const DOC = { id: "doc-1", filename: "Fleet Operations & Maintenance Manual.pdf", document_type: "manual" as const }

const CHUNKS: DocumentChunk[] = [
  { chunk_index: 0, text: "1.0 Toyota Hilux Specifications\nUnloaded: 30 PSI for all four tyres. Heavy cargo: 35 PSI in the front and 45 PSI in the rear." },
  { chunk_index: 1, text: "1.0 Toyota Hilux Specifications\n45 PSI in the rear. Off-road: consult the Maintenance Agent for deflation parameters." },
  { chunk_index: 2, text: "2.0 Company Incident Protocols\nAll severe accidents must be reported within 1 hour to the fleet manager." },
]

function state(overrides: Record<string, unknown> = {}) {
  return { data: CHUNKS, isPending: false, isError: false, ...overrides }
}

describe("preview helpers", () => {
  it("splits the section heading off the first line of a stored chunk", () => {
    expect(splitChunk("2.0 Incident Protocols\nReport within 1 hour.")).toEqual({ heading: "2.0 Incident Protocols", body: "Report within 1 hour." })
    expect(splitChunk("Just running text with no heading line.")).toEqual({ heading: null, body: "Just running text with no heading line." })
    // a first line that is a sentence is text, not a heading
    expect(splitChunk("Report within 1 hour.\nThen call the manager.").heading).toBeNull()
    expect(splitChunk("x".repeat(110) + "\nbody").heading).toBeNull()
    // a two-level breadcrumb is a heading too
    expect(splitChunk("2.0 Company Incident Protocols › Mandatory Incident Reporting Timelines\nReport within 1 hour.").heading).toBe(
      "2.0 Company Incident Protocols › Mandatory Incident Reporting Timelines"
    )
  })

  it("removes the text a chunk repeats from the one before it", () => {
    const previous = "Heavy cargo: 35 PSI in the front and 45 PSI in the rear."
    expect(trimOverlap(previous, "45 PSI in the rear. Off-road: consult the agent.")).toBe("Off-road: consult the agent.")
    expect(trimOverlap(previous, "Something else entirely.")).toBe("Something else entirely.") // no overlap: untouched
    expect(trimOverlap(previous, "rear. Off")).toBe("rear. Off") // too short to be an overlap
  })

  it("groups passages under one heading, shown once, reading as running text without the repeated overlap", () => {
    const sections = buildSections(CHUNKS, 1)

    expect(sections.map((s) => s.heading)).toEqual(["1.0 Toyota Hilux Specifications", "2.0 Company Incident Protocols"])
    expect(sections[0]!.parts.map((p) => [p.index, p.hit])).toEqual([[0, false], [1, true]])
    expect(sections[0]!.parts[1]!.text).toBe("Off-road: consult the Maintenance Agent for deflation parameters.")
    expect(sections[1]!.parts).toHaveLength(1)
  })
})

describe("highlightTerms ignores filler words", () => {
  it("marks the meaningful terms of a question, not 'what', 'the' or 'about'", () => {
    const parts = highlightTerms("What the manual says about tyre pressure", "what does the manual say about tyre pressure")
    const marked = parts.filter((p) => typeof p === "object").map((p) => (p as { mark: string }).mark.toLowerCase())

    expect(marked).toEqual(["manual", "tyre", "pressure"])
  })
})

describe("DocumentPreviewSheet", () => {
  beforeEach(() => {
    mockChunks.mockReset().mockReturnValue(state())
    Element.prototype.scrollIntoView = vi.fn()
  })

  it("shows the document's text as readable sections, with each heading once", () => {
    render(<DocumentPreviewSheet document={DOC} open onOpenChange={vi.fn()} />)

    expect(screen.getByRole("heading", { name: "Fleet Operations & Maintenance Manual.pdf" })).toBeInTheDocument()
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "1.0 Toyota Hilux Specifications",
      "2.0 Company Incident Protocols",
    ])
    expect(screen.getByText("Manual")).toBeInTheDocument()
    expect(screen.getByText("3 passages")).toBeInTheDocument()
    expect(mockChunks).toHaveBeenCalledWith("doc-1", true)
  })

  it("puts the text in a region that scrolls vertically and can be reached with the keyboard", () => {
    render(<DocumentPreviewSheet document={DOC} open onOpenChange={vi.fn()} />)

    const region = screen.getByRole("region", { name: "Document text" })
    expect(region).toHaveClass("overflow-y-auto", "flex-1", "min-h-0")
    expect(region).toHaveAttribute("tabindex", "0")
  })

  it("highlights the matching passage with a background and scrolls it into view", () => {
    render(<DocumentPreviewSheet document={DOC} highlightChunk={2} query="accidents reported" open onOpenChange={vi.fn()} />)

    const passage = document.querySelector('[data-hit="true"]') as HTMLElement
    expect(passage).toHaveAttribute("data-chunk", "2")
    expect(passage).toHaveClass("bg-primary-soft")
    expect(within(passage).getByText("Matching passage:")).toHaveClass("sr-only")
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ block: "center" })
    expect(document.querySelectorAll('[data-hit="true"]')).toHaveLength(1)
  })

  it("marks the search terms wherever they appear, with a background colour", () => {
    render(<DocumentPreviewSheet document={DOC} highlightChunk={2} query="what about severe accidents" open onOpenChange={vi.fn()} />)

    const marks = Array.from(document.querySelectorAll("mark"))
    expect(marks.map((m) => m.textContent?.toLowerCase())).toEqual(["severe", "accidents"])
    expect(marks[0]).toHaveClass("bg-warning-soft")
  })

  it("highlights nothing when it is opened from the library instead of a search", () => {
    render(<DocumentPreviewSheet document={DOC} open onOpenChange={vi.fn()} />)

    expect(document.querySelector("mark")).toBeNull()
    expect(document.querySelector('[data-hit="true"]')).toBeNull()
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled()
  })

  it("renders document text as text, never as HTML", () => {
    mockChunks.mockReturnValue(state({ data: [{ chunk_index: 0, text: "Note <script>alert(1)</script> <b>bold</b>" }] }))
    render(<DocumentPreviewSheet document={DOC} open onOpenChange={vi.fn()} />)

    expect(document.querySelector("script")).toBeNull()
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument()
  })

  it("shows a skeleton while the text loads", () => {
    mockChunks.mockReturnValue(state({ data: undefined, isPending: true }))
    render(<DocumentPreviewSheet document={DOC} open onOpenChange={vi.fn()} />)

    expect(screen.getByLabelText("Loading document text")).toBeInTheDocument()
  })

  it("falls back to the matching passage, highlighted, when the full text cannot be loaded", () => {
    mockChunks.mockReturnValue(state({ data: undefined, isPending: false, isError: true }))
    render(<DocumentPreviewSheet document={DOC} query="tyre pressure" fallbackText="Loaded Hilux tyre pressure is 35 PSI." open onOpenChange={vi.fn()} />)

    expect(screen.getByText(/couldn't be loaded. Showing the matching passage/)).toBeInTheDocument()
    expect(Array.from(document.querySelectorAll("mark")).map((m) => m.textContent)).toEqual(["tyre", "pressure"])
  })

  it("says so when a document has no text yet", () => {
    mockChunks.mockReturnValue(state({ data: [] }))
    render(<DocumentPreviewSheet document={DOC} open onOpenChange={vi.fn()} />)

    expect(screen.getByText("No text is available for this document yet.")).toBeInTheDocument()
  })

  it("does not fetch anything while closed", () => {
    render(<DocumentPreviewSheet document={DOC} open={false} onOpenChange={vi.fn()} />)

    expect(mockChunks).toHaveBeenCalledWith("doc-1", false)
  })
})
