"use client"

import { Children, isValidElement, memo, useState, type ReactNode } from "react"
import { Check, Copy } from "lucide-react"
import Markdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"
import { Button } from "@/components/ui/button"

// The heavy half of a chat message: react-markdown + remark-gfm. Kept in its own module so
// message-bubble.tsx can load it lazily (next/dynamic) instead of shipping it with the page.
// **No rehype-raw** — a passage or model response is never rendered as raw HTML
// (CLAUDE.md §4.5). Links open in a new tab with noopener noreferrer.
//
// Tailwind's reset strips the browser's own styling from headings, lists and quotes, so every element
// a model commonly writes gets its typography here: a reply with a heading, a bulleted list and a bold
// figure reads as structured text, not as a wall of unstyled lines.

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

// The text of a fenced block: react-markdown hands `pre` a single <code> element child.
function textOf(node: ReactNode): string {
  return Children.toArray(node)
    .map((child) => (typeof child === "string" ? child : isValidElement<{ children?: ReactNode }>(child) ? textOf(child.props.children) : ""))
    .join("")
}

// Module-level, so every render passes react-markdown the same objects: a fresh object each
// render would count as new props and re-parse the message.
const PLUGINS = [remarkGfm]
const COMPONENTS: Components = {
  h1: ({ children }) => <h1 className="mt-3 text-base font-semibold text-foreground first:mt-0">{children}</h1>,
  h2: ({ children }) => <h2 className="mt-3 text-base font-semibold text-foreground first:mt-0">{children}</h2>,
  h3: ({ children }) => <h3 className="mt-3 text-sm font-semibold text-foreground first:mt-0">{children}</h3>,
  h4: ({ children }) => <h4 className="mt-2 text-sm font-semibold text-foreground first:mt-0">{children}</h4>,
  h5: ({ children }) => <h5 className="mt-2 text-sm font-medium text-foreground first:mt-0">{children}</h5>,
  h6: ({ children }) => <h6 className="mt-2 text-sm font-medium text-muted-foreground first:mt-0">{children}</h6>,
  p: ({ children }) => <p className="leading-relaxed">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  ul: ({ children }) => <ul className="list-disc space-y-1 pl-5 marker:text-muted-foreground">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal space-y-1 pl-5 marker:text-muted-foreground">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="space-y-2 border-l-2 border-border pl-3 text-muted-foreground">{children}</blockquote>
  ),
  hr: () => <hr className="border-border" />,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="underline">
      {children}
    </a>
  ),
  // A fenced block arrives as <pre><code class="language-x">…</code></pre>; render the pre as our own block (with a
  // copy button) and leave `code` for inline spans only.
  pre: ({ children }) => <CodeBlock>{textOf(children).replace(/\n$/, "")}</CodeBlock>,
  code: ({ children }) => <code className="rounded bg-muted px-1 py-0.5 text-caption">{children}</code>,
  table: ({ children }) => (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-caption">{children}</table>
    </div>
  ),
  th: ({ children }) => <th className="border-b border-border p-1.5 text-left font-medium">{children}</th>,
  td: ({ children }) => <td className="border-b border-border p-1.5">{children}</td>,
}

export const MarkdownContent = memo(function MarkdownContent({ text }: { text: string }) {
  return (
    <div className="space-y-2 break-words">
      <Markdown remarkPlugins={PLUGINS} components={COMPONENTS}>
        {text}
      </Markdown>
    </div>
  )
})

export default MarkdownContent
