"use client"

import { useRef, useState } from "react"
import { ArrowDown } from "lucide-react"
import type { ChatMessage } from "@/lib/schemas/chat"
import { Button } from "@/components/ui/button"
import { MessageBubble } from "./message-bubble"

// The scrollable message list: auto-scrolls to the bottom on new messages
// unless the user has scrolled up, in which case a "Jump to latest" pill
// appears instead (plans/07 §3).
export function ChatThread({ messages, footer }: { messages: ChatMessage[]; footer?: React.ReactNode }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [atBottom, setAtBottom] = useState(true)

  function handleScroll() {
    const el = containerRef.current
    if (!el) return
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 48)
  }

  function scrollToBottom() {
    containerRef.current?.scrollTo({ top: containerRef.current.scrollHeight, behavior: "smooth" })
  }

  return (
    <div className="relative flex-1 overflow-hidden">
      <div ref={containerRef} onScroll={handleScroll} className="h-full space-y-4 overflow-y-auto p-4">
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
        {footer}
      </div>
      {!atBottom ? (
        <Button
          variant="outline"
          size="sm"
          className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full shadow-card"
          onClick={scrollToBottom}
        >
          <ArrowDown className="size-3.5" />
          Jump to latest
        </Button>
      ) : null}
    </div>
  )
}
