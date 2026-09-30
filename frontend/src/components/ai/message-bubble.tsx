"use client"

import { lazy, memo, Suspense } from "react"
import { cn } from "@/lib/utils"
import { resolveAttachmentUrl } from "@/lib/api/uploads"
import type { ChatMessage } from "@/lib/schemas/chat"
import { CitationPill } from "./citation-pill"

// react-markdown + remark-gfm are split into their own chunk and loaded on demand instead of
// with the page. Until they arrive (a moment, once per visit) each message shows its text as
// plain pre-wrapped text — the Suspense fallback — so nothing is hidden meanwhile.
const loadMarkdown = () => import("./markdown-content")
const MarkdownContent = lazy(loadMarkdown)

/** Starts fetching the markdown chunk without rendering anything — call when the chat opens,
 * so by the time a message needs it, it has usually arrived. */
export function preloadMarkdown(): void {
  void loadMarkdown()
}

function PlainText({ text }: { text: string }) {
  return <p className="whitespace-pre-wrap">{text}</p>
}

// One message. Memoised: while a reply streams, only the message whose text changed
// re-renders — the rest of a long conversation is left alone. `content-visibility: auto`
// lets the browser skip layout and paint for messages scrolled out of view (the remembered
// intrinsic size keeps the scrollbar stable), which is what keeps long histories smooth
// without windowing the list.
export const MessageBubble = memo(function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user"
  return (
    <div
      className={cn(
        "flex flex-col gap-2 [contain-intrinsic-size:auto_6rem] [content-visibility:auto]",
        isUser ? "items-end" : "items-start"
      )}
    >
      {message.imageUrl ? (
        // eslint-disable-next-line @next/next/no-img-element -- a user upload served by the API host, not a build asset
        <img
          src={resolveAttachmentUrl(message.imageUrl)}
          alt="Attached photo"
          loading="lazy"
          decoding="async"
          className="max-h-40 max-w-[60%] rounded-lg border border-border object-cover"
        />
      ) : null}
      <div
        className={cn(
          "max-w-[85%] rounded-xl px-4 py-2.5 text-sm",
          isUser ? "bg-primary text-primary-foreground" : "border border-border bg-card text-foreground"
        )}
      >
        <MarkdownOrPlain text={message.text} />
      </div>
      {message.citations && message.citations.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {message.citations.map((hit) => (
            <CitationPill key={`${hit.document_id}-${hit.chunk_index}`} hit={hit} />
          ))}
        </div>
      ) : null}
    </div>
  )
})

function MarkdownOrPlain({ text }: { text: string }) {
  // An empty string (an assistant bubble waiting for its first token) needs no parser.
  if (!text) return <PlainText text="" />
  return (
    <Suspense fallback={<PlainText text={text} />}>
      <MarkdownContent text={text} />
    </Suspense>
  )
}
