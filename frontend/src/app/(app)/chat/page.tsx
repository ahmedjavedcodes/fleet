"use client"

import { useQueryClient } from "@tanstack/react-query"
import { MessageSquare, PanelLeft } from "lucide-react"
import { useRouter, useSearchParams } from "next/navigation"
import { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import {
  approveChatAction,
  createChatSession,
  getChatMessages,
  modifyChatAction,
  rejectChatAction,
  sendChatMessage,
  useChatSessions,
  useRenameChatSession,
  type ChatEvent,
} from "@/lib/api/chat"
import { isApiError } from "@/lib/api/errors"
import { chatKeys } from "@/lib/query/keys"
import type { ChatMessage, HitlState } from "@/lib/schemas/chat"
import { AgentActivity, ApprovalCard, HaltedCard, type ActivityStep } from "@/components/ai/agent-panels"
import { ChatSessionSidebar } from "@/components/ai/chat-session-sidebar"
import { ChatThread } from "@/components/ai/chat-thread"
import { Composer } from "@/components/ai/composer"
import { PageHeader } from "@/components/layout/page-header"
import { EmptyState } from "@/components/states/empty-state"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"

type HistoryState = { status: "idle" } | { status: "loading" } | { status: "error"; message: string }

// A real integration: ai_agents/server.py wraps the Grand Orchestrator
// (OrchestratorSession) in an HTTP/SSE API, proxied through
// /api/proxy-agents. Tool calls it makes hit the real backend.
//
// Two panes: the user's saved conversations on the left, the open one on the right. The URL
// (/chat?session=<id>) is the source of truth for which conversation is open, so switching is
// just navigation and the browser's back button works. A conversation's id is the id of its
// persisted memory session: opening one loads its stored transcript, and every message is sent
// with that id explicitly so it can only ever append to that thread.
export default function ChatPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const urlSessionId = searchParams.get("session")

  const sessionsQuery = useChatSessions()
  const renameMutation = useRenameChatSession()

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [activity, setActivity] = useState<ActivityStep[]>([])
  const [hitlState, setHitlState] = useState<HitlState | null>(null)
  const [haltedReason, setHaltedReason] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [history, setHistory] = useState<HistoryState>({ status: "idle" })
  const [drawerOpen, setDrawerOpen] = useState(false)
  const nextId = useRef(0)
  const abortRef = useRef<AbortController | null>(null)
  // The conversation whose messages this page currently holds, and a counter bumped whenever it
  // is left. A turn still streaming for a conversation that was left must not touch the new one.
  const heldRef = useRef<string | null>(null)
  const epochRef = useRef(0)

  function newId(): string {
    nextId.current += 1
    return `msg-${nextId.current}`
  }

  const resetConversation = useCallback(() => {
    epochRef.current += 1
    abortRef.current?.abort()
    setMessages([])
    setIsStreaming(false)
    setActivity([])
    setHitlState(null)
    setHaltedReason(null)
    setError(null)
    setHistory({ status: "idle" })
  }, [])

  // Follow the URL: a different ?session= (sidebar click, back button, a link) opens that
  // conversation; none means a fresh one.
  useEffect(() => {
    if (urlSessionId === heldRef.current) return
    resetConversation()
    heldRef.current = urlSessionId
    setSessionId(urlSessionId)
    if (!urlSessionId) return

    setHistory({ status: "loading" })
    getChatMessages(urlSessionId)
      .then((rows) => {
        if (heldRef.current !== urlSessionId) return // the user moved on while this loaded
        setMessages(rows.map((m) => ({ id: `stored-${m.id}`, role: m.role, text: m.content })))
        setHistory({ status: "idle" })
      })
      .catch((err: unknown) => {
        if (heldRef.current !== urlSessionId) return
        setHistory({
          status: "error",
          message: isApiError(err) && err.kind === "not_found" ? "That conversation couldn't be found." : "Couldn't load this conversation.",
        })
      })
  }, [urlSessionId, resetConversation])

  function refreshSessions() {
    void queryClient.invalidateQueries({ queryKey: chatKeys.sessions() })
  }

  async function consume(events: AsyncGenerator<ChatEvent>, assistantId: string, epoch: number) {
    let text = ""
    for await (const event of events) {
      if (epoch !== epochRef.current) return
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
    if (epoch !== epochRef.current) return
    setIsStreaming(false)
    setActivity([])
    // The backend titles a conversation from its first message and moves it to the top of
    // the list as it is used, so re-read the list once the turn has landed.
    refreshSessions()
  }

  async function handleSend(text: string) {
    setError(null)
    setHaltedReason(null)
    const epoch = epochRef.current
    const userId = newId()
    const assistantId = newId()
    setMessages((prev) => [...prev, { id: userId, role: "user", text }, { id: assistantId, role: "assistant", text: "" }])
    setIsStreaming(true)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      let sid = sessionId
      if (!sid) {
        // A brand-new chat: create its session first so the id is known (and in the URL) before
        // anything streams, whatever happens to the turn afterwards.
        try {
          sid = await createChatSession()
        } catch (err) {
          if (epoch === epochRef.current) {
            setMessages((prev) => prev.filter((m) => m.id !== userId && m.id !== assistantId))
            setIsStreaming(false)
            setError(isApiError(err) && "message" in err ? err.message : "Couldn't reach the AI assistant.")
          }
          return
        }
        if (epoch !== epochRef.current) return // the user opened another chat meanwhile
        heldRef.current = sid
        setSessionId(sid)
        router.replace(`/chat?session=${sid}`)
      }
      await consume(sendChatMessage(sid, text, controller.signal), assistantId, epoch)
    } catch (err) {
      if (epoch !== epochRef.current) return
      setIsStreaming(false)
      setError(isApiError(err) && "message" in err ? err.message : "Couldn't reach the AI assistant.")
      refreshSessions()
    }
  }

  async function handleApprovalDecision(kind: "approve" | "modify" | "reject", updates?: Record<string, unknown>) {
    if (!sessionId) return
    const epoch = epochRef.current
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
      await consume(events, assistantId, epoch)
    } catch (err) {
      if (epoch !== epochRef.current) return
      setIsStreaming(false)
      setError(isApiError(err) && "message" in err ? err.message : "Couldn't reach the AI assistant.")
    }
  }

  function handleStop() {
    abortRef.current?.abort()
    setIsStreaming(false)
    setActivity([])
  }

  function handleNewChat() {
    setDrawerOpen(false)
    resetConversation()
    heldRef.current = null
    setSessionId(null)
    if (urlSessionId) router.push("/chat")
  }

  function handleSelect(id: string) {
    setDrawerOpen(false)
    if (id !== sessionId) router.push(`/chat?session=${id}`)
  }

  function handleRename(id: string, title: string) {
    renameMutation.mutate(
      { id, title },
      { onError: () => toast.error("Couldn't rename this conversation.") }
    )
  }

  const activeTitle = sessionsQuery.data?.find((s) => s.id === sessionId)?.title ?? "New chat"
  const composerBlocked = history.status !== "idle"

  const sidebar = (
    <ChatSessionSidebar
      sessions={sessionsQuery.data}
      isPending={sessionsQuery.isPending}
      isError={sessionsQuery.isError}
      onRetry={() => void sessionsQuery.refetch()}
      activeId={sessionId}
      onSelect={handleSelect}
      onNew={handleNewChat}
      onRename={handleRename}
    />
  )

  return (
    <div className="flex h-[calc(100vh-6rem)] gap-4">
      <PageHeader crumbs={[{ label: "AI Assistant" }]} />

      <aside aria-label="Conversations" className="hidden w-72 shrink-0 md:flex">
        {sidebar}
      </aside>

      <section aria-label="Chat" className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 pb-2 md:hidden">
          <Button variant="outline" size="sm" onClick={() => setDrawerOpen(true)}>
            <PanelLeft className="size-4" />
            Chats
          </Button>
          <span className="truncate text-sm font-medium text-foreground">{activeTitle}</span>
        </div>

        <ChatThread
          messages={messages}
          footer={
            <div className="space-y-3">
              {history.status === "loading" ? (
                <div role="status" aria-label="Loading conversation" className="space-y-3">
                  <Skeleton className="h-12 w-2/3" />
                  <Skeleton className="ml-auto h-12 w-1/2" />
                  <Skeleton className="h-16 w-3/4" />
                </div>
              ) : null}
              {history.status === "error" ? (
                <div role="alert" className="flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive-soft p-3 text-sm text-foreground">
                  <span>{history.message}</span>
                  <Button variant="outline" size="sm" onClick={handleNewChat}>
                    Start a new chat
                  </Button>
                </div>
              ) : null}
              {history.status === "idle" && messages.length === 0 && !isStreaming ? (
                <EmptyState
                  icon={MessageSquare}
                  title="Start a new conversation"
                  description="Ask about vehicles, maintenance, fuel, drivers or compliance."
                />
              ) : null}
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
          disabled={isStreaming || Boolean(hitlState) || composerBlocked}
          disabledReason={hitlState ? "Waiting on your approval above…" : undefined}
        />
      </section>

      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent side="left" className="w-80 p-3 pt-12">
          <SheetHeader className="sr-only">
            <SheetTitle>Conversations</SheetTitle>
            <SheetDescription>Your saved chats. Pick one to open it, or start a new chat.</SheetDescription>
          </SheetHeader>
          {sidebar}
        </SheetContent>
      </Sheet>
    </div>
  )
}
