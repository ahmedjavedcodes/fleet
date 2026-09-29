"use client"

import { FileText } from "lucide-react"
import Link from "next/link"
import { DOCUMENT_TYPE_LABELS } from "@/lib/enum-labels"
import type { DocumentSearchHit } from "@/lib/schemas/document"
import { Badge } from "@/components/ui/badge"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"

// Passages are untrusted text from a document, never markdown or HTML —
// CLAUDE.md §4.5. Highlighting below is plain string splitting into text
// nodes, never dangerouslySetInnerHTML.
function escapeRegExp(term: string): string {
  return term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

export function highlightTerms(text: string, query: string): (string | { mark: string })[] {
  const terms = query
    .split(/\s+/)
    .map((t) => t.trim())
    .filter((t) => t.length > 1)
  if (terms.length === 0) return [text]
  const pattern = new RegExp(`(${terms.map(escapeRegExp).join("|")})`, "gi")
  return text.split(pattern).map((part) => (terms.some((t) => t.toLowerCase() === part.toLowerCase()) ? { mark: part } : part))
}

function HighlightedText({ text, query }: { text: string; query: string }) {
  return (
    <>
      {highlightTerms(text, query).map((part, i) =>
        typeof part === "string" ? <span key={i}>{part}</span> : <mark key={i}>{part.mark}</mark>
      )}
    </>
  )
}

// A small chip: file icon, filename, type badge (plans/07 §2).
export function CitationPill({ hit, className }: { hit: DocumentSearchHit; className?: string }) {
  return (
    <span className={"inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-caption " + (className ?? "")}>
      <FileText className="size-3.5 text-muted-foreground" aria-hidden />
      <span className="font-medium text-foreground">{hit.filename}</span>
      <Badge variant="outline">{DOCUMENT_TYPE_LABELS[hit.document_type]}</Badge>
    </span>
  )
}

// Hover reveal: filename, type, chunk number, a relevance meter and a
// ~300-char snippet with text-only query-term highlighting.
export function CitationHoverCard({ hit, query, children }: { hit: DocumentSearchHit; query: string; children: React.ReactNode }) {
  return (
    <HoverCard>
      <HoverCardTrigger asChild>{children}</HoverCardTrigger>
      <HoverCardContent className="w-80 space-y-2">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium text-foreground">{hit.filename}</p>
          <Badge variant="outline">{DOCUMENT_TYPE_LABELS[hit.document_type]}</Badge>
        </div>
        <p className="text-caption text-muted-foreground">Chunk {hit.chunk_index}</p>
        <div role="meter" aria-valuenow={hit.relevance} aria-valuemin={0} aria-valuemax={1} className="h-1.5 w-full rounded-full bg-muted">
          <div className="h-full rounded-full bg-primary" style={{ width: `${Math.round(hit.relevance * 100)}%` }} />
        </div>
        <p className="text-caption text-foreground">
          <HighlightedText text={hit.text.slice(0, 300)} query={query} />
        </p>
      </HoverCardContent>
    </HoverCard>
  )
}

// The full passage as plain text, plus a link back to the library.
export function CitationSheet({ hit, query, open, onOpenChange }: { hit: DocumentSearchHit; query: string; open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>{hit.filename}</SheetTitle>
        </SheetHeader>
        <div className="space-y-3 px-4">
          <Badge variant="outline">{DOCUMENT_TYPE_LABELS[hit.document_type]}</Badge>
          <p className="text-sm text-foreground">
            <HighlightedText text={hit.text} query={query} />
          </p>
          <Link href={`/documents?id=${hit.document_id}`} className="text-sm font-medium text-primary-strong hover:underline">
            Open in the document library
          </Link>
        </div>
      </SheetContent>
    </Sheet>
  )
}
