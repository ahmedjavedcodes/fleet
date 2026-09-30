"use client"

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"
import { ArrowDown } from "lucide-react"
import type { ChatMessage } from "@/lib/schemas/chat"
import { Button } from "@/components/ui/button"
import { MessageBubble } from "./message-bubble"

// How close to the bottom still counts as "following the conversation".
const PIN_THRESHOLD_PX = 48

function latestUserMessageId(messages: ChatMessage[]): string | undefined {
  for (let i = messages.length - 1; i >= 0; i--) if (messages[i]!.role === "user") return messages[i]!.id
  return undefined
}

// The scrollable message list. It follows the conversation — new messages, a streaming
// reply, an image finishing loading — only while the user is at (or near) the bottom; once
// they scroll up to read, it stays put and offers "Jump to latest" instead (plans/07 §3).
//
// Cheap by construction: whether we're pinned lives in a ref, so scrolling never re-renders
// anything (state flips only when the pill has to appear/disappear); and one ResizeObserver
// on the content does the following, so a burst of streamed tokens costs one scroll write
// per layout change rather than one per token.
export function ChatThread({ messages, footer }: { messages: ChatMessage[]; footer?: React.ReactNode }) {
  const scrollerRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)
  const [showJump, setShowJump] = useState(false)

  const scrollToBottom = useCallback((smooth: boolean) => {
    const el = scrollerRef.current
    if (!el) return
    if (smooth) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" })
    else el.scrollTop = el.scrollHeight
  }, [])

  // Passive, and state-free unless the pill's visibility actually changes.
  //
  // Only an UPWARD scroll unpins. Being "not at the bottom" isn't enough: off-screen messages
  // are laid out at an estimated height (content-visibility), so right after we jump to the
  // bottom the real heights arrive and the bottom moves away — without the user doing
  // anything. Content growing never moves scrollTop backwards; a user scrolling up does.
  const lastScrollTop = useRef(0)
  useEffect(() => {
    const el = scrollerRef.current
    if (!el) return
    function onScroll() {
      const node = scrollerRef.current!
      const atBottom = node.scrollHeight - node.scrollTop - node.clientHeight < PIN_THRESHOLD_PX
      const movedUp = node.scrollTop < lastScrollTop.current - 1
      lastScrollTop.current = node.scrollTop
      const nextPinned = atBottom ? true : movedUp ? false : pinned.current
      if (nextPinned !== pinned.current) {
        pinned.current = nextPinned
        setShowJump(!nextPinned)
      }
      // Still following but the bottom moved (heights settled): catch up.
      if (nextPinned && !atBottom) node.scrollTop = node.scrollHeight
    }
    el.addEventListener("scroll", onScroll, { passive: true })
    return () => el.removeEventListener("scroll", onScroll)
  }, [])

  // Content grew (streamed text, a new message, an image decoded): follow it if pinned.
  useEffect(() => {
    const content = contentRef.current
    if (!content || typeof ResizeObserver === "undefined") return
    const observer = new ResizeObserver(() => {
      if (pinned.current) scrollToBottom(false)
    })
    observer.observe(content)
    return () => observer.disconnect()
  }, [scrollToBottom])

  // The user just sent a message (or a conversation was opened): jump to the latest, even if
  // they had scrolled up. Keyed on the newest user message, so streamed tokens never trigger it.
  const lastUserId = latestUserMessageId(messages)
  const previousUserId = useRef<string | undefined>(undefined)
  useLayoutEffect(() => {
    if (lastUserId && lastUserId !== previousUserId.current) {
      pinned.current = true
      setShowJump(false)
      scrollToBottom(false)
    }
    previousUserId.current = lastUserId
  }, [lastUserId, scrollToBottom])

  return (
    // min-h-0: a flex item's minimum height defaults to its content's, so without it a long
    // conversation grew the thread past its container, pushing the composer down and leaving
    // the page scrolling with empty space under it, instead of scrolling inside the thread.
    <div className="relative min-h-0 flex-1 overflow-hidden" data-testid="chat-thread">
      <div ref={scrollerRef} className="h-full overflow-y-auto overscroll-contain">
        <div ref={contentRef} className="space-y-4 p-4">
          {messages.map((m) => (
            <MessageBubble key={m.id} message={m} />
          ))}
          {footer}
        </div>
      </div>
      {showJump ? (
        <Button
          variant="outline"
          size="sm"
          className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full shadow-card"
          onClick={() => {
            pinned.current = true
            setShowJump(false)
            scrollToBottom(true)
          }}
        >
          <ArrowDown className="size-3.5" />
          Jump to latest
        </Button>
      ) : null}
    </div>
  )
}
