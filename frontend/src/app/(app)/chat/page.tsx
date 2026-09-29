"use client"

import { useRef, useState } from "react"
import { approveChatAction, modifyChatAction, rejectChatAction, sendChatMessage, type ChatEvent } from "@/lib/api/chat"
import { isApiError } from "@/lib/api/errors"
import type { ChatMessage, HitlState } from "@/lib/schemas/chat"
import { AgentActivity, ApprovalCard, HaltedCard, type ActivityStep } from "@/components/ai/agent-panels"
import { ChatThread } from "@/components/ai/chat-thread"
import { Composer } from "@/components/ai/composer"
import { PageHeader } from "@/components/layout/page-header"

// A real integration: ai_agents/server.py wraps the Grand Orchestrator
// (OrchestratorSession) in an HTTP/SSE API, proxied through
// /api/proxy-agents. Tool calls it makes hit the real backend.
export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sessionId, setSessionId] = useState<string | undefined>(undefined)
  const [isStreaming, setIsStreaming] = useState(false)
  const [activity, setActivity] = useState<ActivityStep[]>([])
  const [hitlState, setHitlState] = useState<HitlState | null>(null)
  const [haltedReason, setHaltedReason] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const nextId = useRef(0)
  const abortRef = useRef<AbortController | null>(null)

  function newId(): string {
    nextId.current += 1
    return `msg-${nextId.current}`
  }

  async function consume(sid: string, events: AsyncGenerator<ChatEvent>, assistantId: string) {
    let text = ""
    for await (const event of events) {
      if (event.type === "activity") {
        setActivity((prev) => {
          const others = prev.filter((s) => s.agent !== event.agent || s.step !== event.step)
          return [...others, { agent: event.agent, step: event.step, done: event.done }]
        })
      } else if (event.type === "token") {
        text += event.text
        setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, text } : m)))
      } else if (event.type === "approval_required") {
        setHitlState(event.hitl_state)
      } else if (event.type === "done") {
        if (event.status === "halted" && text) setHaltedReason(text)
      } else if (event.type === "error") {
        setError(event.message)
      }
    }
    setSessionId(sid)
    setIsStreaming(false)
    setActivity([])
  }

  async function handleSend(text: string) {
    setError(null)
    setHaltedReason(null)
    const userMessage: ChatMessage = { id: newId(), role: "user", text }
    const assistantId = newId()
    setMessages((prev) => [...prev, userMessage, { id: assistantId, role: "assistant", text: "" }])
    setIsStreaming(true)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const { sessionId: sid, events } = await sendChatMessage(text, sessionId, controller.signal)
      await consume(sid, events, assistantId)
    } catch (err) {
      setIsStreaming(false)
      setError(isApiError(err) && "message" in err ? err.message : "Couldn't reach the AI assistant.")
    }
  }

  async function handleApprovalDecision(kind: "approve" | "modify" | "reject", updates?: Record<string, unknown>) {
    if (!sessionId) return
    setHitlState(null)
    const assistantId = newId()
    setMessages((prev) => [...prev, { id: assistantId, role: "assistant", text: "" }])
    setIsStreaming(true)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const events =
        kind === "approve"
          ? approveChatAction(sessionId, controller.signal)
          : kind === "modify" && updates
            ? modifyChatAction(sessionId, updates, controller.signal)
            : rejectChatAction(sessionId, controller.signal)
      await consume(sessionId, events, assistantId)
    } catch (err) {
      setIsStreaming(false)
      setError(isApiError(err) && "message" in err ? err.message : "Couldn't reach the AI assistant.")
    }
  }

  function handleStop() {
    abortRef.current?.abort()
    setIsStreaming(false)
    setActivity([])
  }

  return (
    <div className="flex h-[calc(100vh-6rem)] flex-col">
      <PageHeader crumbs={[{ label: "AI Assistant" }]} />

      <ChatThread
        messages={messages}
        footer={
          <div className="space-y-3">
            {isStreaming && activity.length > 0 ? <AgentActivity steps={activity} /> : null}
            {hitlState ? (
              <ApprovalCard
                hitlState={hitlState}
                onApprove={() => void handleApprovalDecision("approve")}
                onModify={(notes) => void handleApprovalDecision("modify", { notes })}
                onReject={() => void handleApprovalDecision("reject")}
              />
            ) : null}
            {haltedReason ? <HaltedCard reason={haltedReason} /> : null}
            {error ? (
              <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive-soft p-3 text-sm text-foreground">
                {error}
              </div>
            ) : null}
          </div>
        }
      />

      <Composer
        onSend={(text) => void handleSend(text)}
        onStop={handleStop}
        isStreaming={isStreaming}
        disabled={isStreaming || Boolean(hitlState)}
        disabledReason={hitlState ? "Waiting on your approval above…" : undefined}
      />
    </div>
  )
}
