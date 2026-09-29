"use client"

import { useState } from "react"
import { Check, Copy } from "lucide-react"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { cn } from "@/lib/utils"
import type { ChatMessage } from "@/lib/schemas/chat"
import { Button } from "@/components/ui/button"
import { CitationPill } from "./citation-pill"

function CodeBlock({ children }: { children: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="relative">
      <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-caption">
        <code>{children}</code>
      </pre>
      <Button
        variant="ghost"
        size="icon-sm"
        className="absolute top-1.5 right-1.5"
        aria-label="Copy code"
        onClick={() => {
          void navigator.clipboard.writeText(children)
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        }}
      >
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      </Button>
    </div>
  )
}

// A single message: react-markdown + remark-gfm for tables/lists/code,
// **no rehype-raw** — a passage or model response is never rendered as raw
// HTML (CLAUDE.md §4.5). Links open in a new tab with noopener noreferrer.
export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user"
  return (
    <div className={cn("flex flex-col gap-2", isUser ? "items-end" : "items-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-xl px-4 py-2.5 text-sm",
          isUser ? "bg-primary text-primary-foreground" : "border border-border bg-card text-foreground"
        )}
      >
        <Markdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ href, children }) => (
              <a href={href} target="_blank" rel="noopener noreferrer" className="underline">
                {children}
              </a>
            ),
            code: ({ className, children }) =>
              className ? <CodeBlock>{String(children)}</CodeBlock> : <code className="rounded bg-muted px-1 py-0.5">{children}</code>,
            table: ({ children }) => <table className="w-full border-collapse text-caption">{children}</table>,
            th: ({ children }) => <th className="border-b border-border p-1.5 text-left font-medium">{children}</th>,
            td: ({ children }) => <td className="border-b border-border p-1.5">{children}</td>,
          }}
        >
          {message.text}
        </Markdown>
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
}
