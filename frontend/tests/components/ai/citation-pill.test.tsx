import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { CitationPill, highlightTerms } from "@/components/ai/citation-pill"
import type { DocumentSearchHit } from "@/lib/schemas/document"

const HIT: DocumentSearchHit = {
  document_id: "11111111-1111-1111-1111-111111111111",
  filename: "brake-service-manual.pdf",
  document_type: "manual",
  chunk_index: 3,
  text: "Replace brake pads every 20,000 km or when thickness falls below 3mm.",
  relevance: 0.82,
}

describe("CitationPill", () => {
  it("renders the filename and a type badge", () => {
    render(<CitationPill hit={HIT} />)
    expect(screen.getByText("brake-service-manual.pdf")).toBeInTheDocument()
    expect(screen.getByText("Manual")).toBeInTheDocument()
  })
})

describe("highlightTerms", () => {
  it("splits text into plain and marked parts on query terms, case-insensitively", () => {
    const parts = highlightTerms("Replace brake pads soon", "brake")
    const marked = parts.filter((p) => typeof p === "object") as { mark: string }[]
    expect(marked.map((m) => m.mark.toLowerCase())).toEqual(["brake"])
  })

  it("never treats the query as HTML/regex injection — special characters are literal", () => {
    const parts = highlightTerms("Cost is $5 (approx)", "$5")
    const flattened = parts.map((p) => (typeof p === "string" ? p : p.mark)).join("")
    expect(flattened).toBe("Cost is $5 (approx)")
  })

  it("returns the text unchanged when the query has no usable terms", () => {
    expect(highlightTerms("some text", " ")).toEqual(["some text"])
  })
})
