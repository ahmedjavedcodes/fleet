"use client"

import { memo, useState } from "react"
import { Check, Copy } from "lucide-react"
import Markdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"
import { Button } from "@/components/ui/button"

// The heavy half of a chat message: react-markdown + remark-gfm. Kept in its own module so
// message-bubble.tsx can load it lazily (next/dynamic) instead of shipping it with the page.
// **No rehype-raw** — a passage or model response is never rendered as raw HTML
// (CLAUDE.md §4.5). Links open in a new tab with noopener noreferrer.

const CodeBlock = memo(function CodeBlock({ children }: { children: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="relative">
      {/* pr-10 keeps the copy button from covering the end of a long line. */}
      <pre className="overflow-x-auto rounded-lg bg-muted p-3 pr-10 text-caption">
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
})

// Module-level, so every render passes react-markdown the same objects: a fresh object each
// render would count as new props and re-parse the message.
const PLUGINS = [remarkGfm]
const COMPONENTS: Components = {
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
}

export const MarkdownContent = memo(function MarkdownContent({ text }: { text: string }) {
  return (
    <Markdown remarkPlugins={PLUGINS} components={COMPONENTS}>
      {text}
    </Markdown>
  )
})

export default MarkdownContent
