import { act, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { ChatMessage } from "@/lib/schemas/chat"

// Counts how often a message's markdown is actually rendered, so the tests can prove that a
// streaming reply or a scroll leaves every other message alone.
const markdownRenders = vi.fn()
vi.mock("@/components/ai/markdown-content", async () => {
  const { memo } = await import("react")
  const MarkdownContent = memo(function MarkdownContent({ text }: { text: string }) {
    markdownRenders(text)
    return <p data-testid="markdown">{text}</p>
  })
  return { MarkdownContent, default: MarkdownContent }
})

const { ChatThread } = await import("@/components/ai/chat-thread")
const { MessageBubble } = await import("@/components/ai/message-bubble")

function history(n: number): ChatMessage[] {
  return Array.from({ length: n }, (_, i) => ({ id: `m${i}`, role: i % 2 ? "assistant" : "user", text: `message ${i}` }))
}

// Wait for the lazily loaded markdown (not the plain-text fallback) to be on screen.
async function waitForMarkdown(count: number) {
  await waitFor(() => expect(screen.getAllByTestId("markdown")).toHaveLength(count), { timeout: 15000 })
}

// Real usage: the view is pinned at the bottom, then the user scrolls up to `to`.
function scrollUpFromBottom(el: HTMLElement, to: number) {
  act(() => {
    el.scrollTop = el.scrollHeight
    el.dispatchEvent(new Event("scroll"))
    el.scrollTop = to
    el.dispatchEvent(new Event("scroll"))
  })
}

let resizeCallbacks: Array<() => void> = []

beforeEach(() => {
  markdownRenders.mockReset()
  resizeCallbacks = []
  globalThis.ResizeObserver = class {
    constructor(cb: () => void) {
      resizeCallbacks.push(cb)
    }
    observe() {}
    disconnect() {}
    unobserve() {}
  } as unknown as typeof ResizeObserver
})

// The scroller is the thread's first child; jsdom has no layout, so give it geometry.
function scroller(): HTMLDivElement {
  return screen.getByTestId("chat-thread").firstElementChild as HTMLDivElement
}
function setGeometry(el: HTMLElement, { scrollHeight, clientHeight }: { scrollHeight: number; clientHeight: number }) {
  Object.defineProperty(el, "scrollHeight", { configurable: true, value: scrollHeight })
  Object.defineProperty(el, "clientHeight", { configurable: true, value: clientHeight })
}

describe("streaming re-renders only the message that changed", () => {
  it("a new token re-renders one markdown block, not the whole 200-message history", async () => {
    const messages = history(200)
    const { rerender } = render(<ChatThread messages={messages} />)
    await waitForMarkdown(200)
    markdownRenders.mockClear()

    const streamed = [...messages.slice(0, -1), { ...messages[199]!, text: "message 199 and more" }]
    rerender(<ChatThread messages={streamed} />)

    expect(markdownRenders).toHaveBeenCalledTimes(1)
    expect(markdownRenders).toHaveBeenCalledWith("message 199 and more")
  }, 30000) // jsdom renders 200 messages slowly; the assertion, not the wall clock, is the point

  it("re-rendering with identical messages renders no markdown at all", async () => {
    const messages = history(50)
    const { rerender } = render(<ChatThread messages={messages} footer={<p>footer A</p>} />)
    await waitForMarkdown(50)
    markdownRenders.mockClear()

    rerender(<ChatThread messages={messages} footer={<p>footer B</p>} />) // e.g. an activity step changed

    expect(markdownRenders).not.toHaveBeenCalled()
  })

  it("shows the plain text immediately while the markdown chunk loads", () => {
    render(<MessageBubble message={{ id: "x", role: "assistant", text: "fallback text" }} />)
    expect(screen.getByText("fallback text")).toBeInTheDocument()
  })
})

describe("auto-scroll", () => {
  it("follows new content while the user is at the bottom", async () => {
    render(<ChatThread messages={history(5)} />)
    await waitForMarkdown(5)
    const el = scroller()
    setGeometry(el, { scrollHeight: 2000, clientHeight: 500 })

    act(() => resizeCallbacks.forEach((cb) => cb())) // content grew (a streamed token)

    expect(el.scrollTop).toBe(2000)
  })

  it("leaves the view alone once the user scrolls up, and offers Jump to latest instead", async () => {
    render(<ChatThread messages={history(5)} />)
    await waitForMarkdown(5)
    const el = scroller()
    setGeometry(el, { scrollHeight: 2000, clientHeight: 500 })
    scrollUpFromBottom(el, 100)

    act(() => resizeCallbacks.forEach((cb) => cb()))

    expect(el.scrollTop).toBe(100)
    expect(screen.getByRole("button", { name: "Jump to latest" })).toBeInTheDocument()
  })

  it("stays pinned when the bottom moves away because heights settled, not because the user scrolled", async () => {
    render(<ChatThread messages={history(5)} />)
    await waitForMarkdown(5)
    const el = scroller()
    setGeometry(el, { scrollHeight: 2000, clientHeight: 500 })
    act(() => resizeCallbacks.forEach((cb) => cb()))
    expect(el.scrollTop).toBe(2000)

    // Estimated heights resolve to real ones: the content is taller, scrollTop hasn't moved.
    setGeometry(el, { scrollHeight: 2600, clientHeight: 500 })
    act(() => {
      el.dispatchEvent(new Event("scroll"))
    })

    expect(el.scrollTop).toBe(2600) // caught up, still following
    expect(screen.queryByRole("button", { name: "Jump to latest" })).not.toBeInTheDocument()
  })

  it("scrolling never re-renders the messages", async () => {
    render(<ChatThread messages={history(100)} />)
    await waitForMarkdown(100)
    const el = scroller()
    setGeometry(el, { scrollHeight: 5000, clientHeight: 500 })
    markdownRenders.mockClear()

    act(() => {
      for (const y of [0, 400, 800, 1200]) {
        el.scrollTop = y
        el.dispatchEvent(new Event("scroll"))
      }
    })

    expect(markdownRenders).not.toHaveBeenCalled()
  })

  it("the user's own new message always brings the view back to the bottom", async () => {
    const messages = history(5)
    const { rerender } = render(<ChatThread messages={messages} />)
    await waitForMarkdown(5)
    const el = scroller()
    setGeometry(el, { scrollHeight: 2000, clientHeight: 500 })
    scrollUpFromBottom(el, 100)

    setGeometry(el, { scrollHeight: 2300, clientHeight: 500 })
    rerender(<ChatThread messages={[...messages, { id: "new", role: "user", text: "a new question" }]} />)

    expect(el.scrollTop).toBe(2300)
    expect(screen.queryByRole("button", { name: "Jump to latest" })).not.toBeInTheDocument()
  })
})
