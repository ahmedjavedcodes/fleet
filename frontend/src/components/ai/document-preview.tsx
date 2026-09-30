"use client"

import { AlertCircle } from "lucide-react"
import { useMemo } from "react"
import { useDocumentChunks } from "@/lib/api/documents"
import { DOCUMENT_TYPE_LABELS } from "@/lib/enum-labels"
import type { DocumentChunk } from "@/lib/schemas/document"
import type { DocumentType } from "@/lib/schemas/enums"
import { HighlightedText } from "@/components/ai/highlight"
import { Badge } from "@/components/ui/badge"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"

export type PreviewDocument = { id: string; filename: string; document_type: DocumentType }

const MAX_HEADING_CHARS = 100 // the backend cuts its "Section › Sub-section" breadcrumb at 90
const MIN_OVERLAP_CHARS = 10
const MAX_OVERLAP_CHARS = 80

// The backend stores each chunk as "<section heading>\n<text>" (services/document_chunking.py): a short first
// line that names the section, then the passage. A chunk with no such first line is all text.
export function splitChunk(text: string): { heading: string | null; body: string } {
  const newline = text.indexOf("\n")
  if (newline === -1) return { heading: null, body: text }
  const first = text.slice(0, newline).trim()
  if (first.length > 0 && first.length <= MAX_HEADING_CHARS && !/[.,;:!?]$/.test(first)) {
    return { heading: first, body: text.slice(newline + 1).trim() }
  }
  return { heading: null, body: text }
}

// Neighbouring chunks repeat a little text (about 50 characters) so a fact that straddles a boundary survives.
// When the passages are read back to back, that repeat is removed so the text flows.
export function trimOverlap(previous: string, body: string): string {
  const longest = Math.min(MAX_OVERLAP_CHARS, previous.length, body.length)
  for (let size = longest; size >= MIN_OVERLAP_CHARS; size--) {
    if (previous.endsWith(body.slice(0, size))) return body.slice(size).trimStart()
  }
  return body
}

type Part = { index: number; text: string; hit: boolean }
type Section = { heading: string | null; parts: Part[] }

// Consecutive passages under one heading read as one section: the heading is shown once, the passages follow
// each other as running text.
export function buildSections(chunks: DocumentChunk[], highlightChunk: number | undefined): Section[] {
  const sections: Section[] = []
  let previousBody = ""
  for (const chunk of chunks) {
    const { heading, body } = splitChunk(chunk.text)
    const current = sections[sections.length - 1]
    const continues = current !== undefined && current.heading === heading
    const text = continues ? trimOverlap(previousBody, body) : body
    previousBody = body
    if (!text) continue
    const part: Part = { index: chunk.chunk_index, text, hit: chunk.chunk_index === highlightChunk }
    if (continues) current.parts.push(part)
    else sections.push({ heading, parts: [part] })
  }
  return sections
}

// jsdom has no scrollIntoView; real browsers do, and this is what brings the matching passage on screen.
function scrollToPassage(element: HTMLElement | null): void {
  element?.scrollIntoView?.({ block: "center" })
}

// The document as readable text, in a panel that scrolls vertically. When opened from a search result,
// `highlightChunk` marks the matching passage with a background colour (and scrolls to it) and `query`'s terms are
// marked wherever they appear. `fallbackText` is the passage itself, shown if the full text can't be loaded.
// All text is rendered as plain text nodes, never as HTML (CLAUDE.md §4.5).
export function DocumentPreviewSheet({
  document,
  highlightChunk,
  query = "",
  fallbackText,
  open,
  onOpenChange,
}: {
  document: PreviewDocument
  highlightChunk?: number
  query?: string
  fallbackText?: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const chunksQuery = useDocumentChunks(document.id, open)
  const chunks = chunksQuery.data
  const sections = useMemo(() => (chunks ? buildSections(chunks, highlightChunk) : []), [chunks, highlightChunk])

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="data-[side=right]:sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>{document.filename}</SheetTitle>
          <SheetDescription asChild>
            <div className="flex items-center gap-2">
              <Badge variant="outline">{DOCUMENT_TYPE_LABELS[document.document_type]}</Badge>
              {chunks && chunks.length > 0 ? <span>{chunks.length} passages</span> : null}
            </div>
          </SheetDescription>
        </SheetHeader>

        <div
          role="region"
          aria-label="Document text"
          tabIndex={0}
          className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 pb-6 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          {chunksQuery.isPending ? (
            <div className="space-y-2" aria-label="Loading document text">
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          ) : sections.length > 0 ? (
            sections.map((section, i) => (
              <section key={`${section.heading ?? "untitled"}-${i}`} className="space-y-1.5">
                {section.heading ? <h3 className="text-sm font-semibold text-foreground">{section.heading}</h3> : null}
                <p className="text-sm leading-relaxed whitespace-pre-line text-foreground">
                  {section.parts.map((part) => (
                    <span
                      key={part.index}
                      data-chunk={part.index}
                      data-hit={part.hit ? "true" : undefined}
                      ref={part.hit ? scrollToPassage : undefined}
                      className={part.hit ? "rounded-sm bg-primary-soft box-decoration-clone px-0.5" : undefined}
                    >
                      {part.hit ? <span className="sr-only">Matching passage: </span> : null}
                      <HighlightedText text={part.text} query={query} />{" "}
                    </span>
                  ))}
                </p>
              </section>
            ))
          ) : fallbackText ? (
            <div className="space-y-2">
              <p className="flex items-center gap-1.5 text-caption text-muted-foreground">
                <AlertCircle className="size-3.5" aria-hidden />
                {chunksQuery.isError ? "The full text couldn't be loaded. Showing the matching passage." : "Showing the matching passage."}
              </p>
              <p className="rounded-sm bg-primary-soft px-0.5 text-sm leading-relaxed text-foreground">
                <HighlightedText text={fallbackText} query={query} />
              </p>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              {chunksQuery.isError ? "The document text couldn't be loaded." : "No text is available for this document yet."}
            </p>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
