// Search-term highlighting for document text. Passages are untrusted text from a document, never markdown or HTML —
// CLAUDE.md §4.5. Highlighting is plain string splitting into text nodes, never dangerouslySetInnerHTML.

// Words that say nothing about what is being looked for. A question such as "what does the manual say about tyre
// pressure" should light up "tyre" and "pressure", not every "the" and "about" on the page.
const STOP_WORDS = new Set([
  "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "how", "i", "if", "in", "is",
  "it", "me", "my", "of", "on", "or", "our", "say", "says", "show", "tell", "that", "the", "their", "this", "to",
  "was", "we", "what", "when", "where", "which", "who", "why", "will", "with", "you", "your", "about", "according",
])

function escapeRegExp(term: string): string {
  return term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

export function highlightTerms(text: string, query: string): (string | { mark: string })[] {
  const terms = query
    .split(/\s+/)
    .map((t) => t.trim())
    .filter((t) => t.length > 1 && !STOP_WORDS.has(t.toLowerCase().replace(/^\W+|\W+$/g, "")))
  if (terms.length === 0) return [text]
  const pattern = new RegExp(`(${terms.map(escapeRegExp).join("|")})`, "gi")
  return text.split(pattern).map((part) => (terms.some((t) => t.toLowerCase() === part.toLowerCase()) ? { mark: part } : part))
}

// Matches are marked with a background colour, from the design tokens, so they stand out in both themes.
export function HighlightedText({ text, query }: { text: string; query: string }) {
  return (
    <>
      {highlightTerms(text, query).map((part, i) =>
        typeof part === "string" ? (
          <span key={i}>{part}</span>
        ) : (
          <mark key={i} className="rounded-sm bg-warning-soft px-0.5 text-foreground">
            {part.mark}
          </mark>
        )
      )}
    </>
  )
}
