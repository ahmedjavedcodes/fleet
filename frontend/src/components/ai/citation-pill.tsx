"use client"

import { FileText } from "lucide-react"
import { DOCUMENT_TYPE_LABELS } from "@/lib/enum-labels"
import type { DocumentSearchHit } from "@/lib/schemas/document"
import { Badge } from "@/components/ui/badge"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import { DocumentPreviewSheet } from "@/components/ai/document-preview"
import { HighlightedText, highlightTerms } from "@/components/ai/highlight"

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

// A search hit opened in the document preview: the whole document as readable text, scrolled to the matching passage,
// which is highlighted along with the search terms. The passage itself is the fallback if the text can't be loaded.
export function CitationSheet({ hit, query, open, onOpenChange }: { hit: DocumentSearchHit; query: string; open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <DocumentPreviewSheet
      document={{ id: hit.document_id, filename: hit.filename, document_type: hit.document_type }}
      highlightChunk={hit.chunk_index}
      query={query}
      fallbackText={hit.text}
      open={open}
      onOpenChange={onOpenChange}
    />
  )
}

// Kept for callers that import it from here.
export { highlightTerms }
