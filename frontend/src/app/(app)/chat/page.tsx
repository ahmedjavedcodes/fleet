"use client"

import { useQueryClient } from "@tanstack/react-query"
import { MessageSquare, PanelLeft } from "lucide-react"
import { useRouter, useSearchParams } from "next/navigation"
import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import {
  approveChatAction,
  createChatSession,
  getChatMessages,
  modifyChatAction,
  rejectChatAction,
  sendChatMessage,
  useChatSessions,
  useDeleteChatSession,
  useRenameChatSession,
  type ChatEvent,
} from "@/lib/api/chat"
import { uploadDocument, useDocuments, waitForDocumentReady } from "@/lib/api/documents"
import { isApiError } from "@/lib/api/errors"
import { uploadImage } from "@/lib/api/uploads"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import { uploadableDocumentTypes } from "@/lib/document-types"
import { chatKeys, documentKeys } from "@/lib/query/keys"
import { can } from "@/lib/rbac"
import type { ChatMessage, HitlState } from "@/lib/schemas/chat"
import { AgentActivity, HaltedCard, type ActivityStep } from "@/components/ai/agent-panels"
import { ChatSessionSidebar } from "@/components/ai/chat-session-sidebar"
import { ChatThread } from "@/components/ai/chat-thread"
import { preloadMarkdown } from "@/components/ai/message-bubble"
import { Composer, type ComposerExtras, type MentionableDocument } from "@/components/ai/composer"
import { DocumentUploadCard, type UploadPhase } from "@/components/ai/document-upload-card"
import { PageHeader } from "@/components/layout/page-header"
import { EmptyState } from "@/components/states/empty-state"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"

// Only needed when an action is waiting on approval, so it (and Radix AlertDialog) load then.
const ApprovalCard = lazy(() => import("@/components/ai/approval-card"))

// A function with a fixed identity that always runs the latest version of `fn`. Lets the
// memoised sidebar and composer keep their props stable across the page re-rendering on every
// streamed frame, without threading every piece of state through dependency lists. Only for
// callbacks run from events, never during render.
function useStableCallback<A extends unknown[], R>(fn: (...args: A) => R): (...args: A) => R {
  const ref = useRef(fn)
  useLayoutEffect(() => {
    ref.current = fn
  })
  return useCallback((...args: A) => ref.current(...args), [])
}

// Sent when a photo goes out with no typed text, so the turn still has a request to act on.
const IMAGE_ONLY_MESSAGE = "Please process the attached image."
// Likewise for a PDF sent with no typed text.
const PDF_ONLY_MESSAGE = "Summarize this document."

type HistoryState ={ status: "idle" } | { status: "loading" } | { status: "error"; message: string }

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
  const deleteMutation = useDeleteChatSession()

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [activity, setActivity] = useState<ActivityStep[]>([])
  const [hitlState, setHitlState] = useState<HitlState | null>(null)
  const [haltedReason, setHaltedReason] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [history, setHistory] = useState<HistoryState>({ status: "idle" })
  const [drawerOpen, setDrawerOpen] = useState(false)
  // A PDF attached to the message being sent: uploaded, then waited on until it has been processed.
  const [pdfUpload, setPdfUpload] = useState<{ filename: string; phase: UploadPhase } | null>(null)
  const nextId = useRef(0)
  const abortRef = useRef<AbortController | null>(null)
  const uploadAbortRef = useRef<AbortController | null>(null)

  // "@" mentions list the documents the user can search (ready ones only); a PDF can be attached only by roles
  // that may upload documents. The backend enforces both; this only decides what the composer offers.
  const { role } = useCurrentUser()
  const canSearchDocuments = Boolean(role && can(role, "document:search"))
  const documentsQuery = useDocuments({ enabled: canSearchDocuments })
  const mentionable = useMemo<MentionableDocument[] | undefined>(
    () =>
      canSearchDocuments
        ? (documentsQuery.data ?? [])
            .filter((d) => d.status === "ready")
            .map((d) => ({ id: d.id, filename: d.filename, document_type: d.document_type }))
        : undefined,
    [canSearchDocuments, documentsQuery.data]
  )
  const pdfTypes = useMemo(() => uploadableDocumentTypes(role), [role])
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
    uploadAbortRef.current?.abort()
    setPdfUpload(null)
    setMessages([])
    setIsStreaming(false)
    setActivity([])
    setHitlState(null)
    setHaltedReason(null)
    setError(null)
    setHistory({ status: "idle" })
  }, [])

  // The markdown renderer is its own lazily loaded chunk; start fetching it as the chat opens.
  useEffect(() => {
    preloadMarkdown()
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
    // Tokens can arrive far faster than the screen refreshes. Accumulate them and commit the
    // text at most once per animation frame, instead of one React update (and re-render) per
    // token; the final text is always flushed when the stream ends.
    let frame: number | null = null
    const flush = () => {
      frame = null
      if (epoch !== epochRef.current) return
      const snapshot = text
      setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, text: snapshot } : m)))
    }
    try {
      for await (const event of events) {
        if (epoch !== epochRef.current) return
        if (event.type === "activity") {
          setActivity((prev) => {
            const others = prev.filter((s) => s.agent !== event.agent || s.step !== event.step)
            return [...others, { agent: event.agent, step: event.step, done: event.done }]
          })
        } else if (event.type === "token") {
          text += event.text
          frame ??= requestAnimationFrame(flush)
        } else if (event.type === "approval_required") {
          setHitlState(event.hitl_state)
        } else if (event.type === "done") {
          if (event.status === "halted" && text) setHaltedReason(text)
        } else if (event.type === "error") {
          setError(event.message)
        }
      }
    } finally {
      if (frame !== null) cancelAnimationFrame(frame)
      if (text) flush()
    }
    if (epoch !== epochRef.current) return
    // A turn that produced no reply text (it failed, or paused for approval) must not leave an
    // empty bubble behind; the error or approval card says what happened.
    if (!text) setMessages((prev) => prev.filter((m) => m.id !== assistantId))
    setIsStreaming(false)
    setActivity([])
    // The backend titles a conversation from its first message and moves it to the top of
    // the list as it is used, so re-read the list once the turn has landed.
    refreshSessions()
  }

  // Resolves once the message is accepted (photo uploaded, session known) — false if it
  // wasn't, so the composer keeps the text and photo. The reply then streams on its own.
  async function handleSend(typed: string, image: File | null, extras?: ComposerExtras): Promise<boolean> {
    setError(null)
    setHaltedReason(null)
    const epoch = epochRef.current

    // Documents this message is about: the ones @-mentioned, plus an attached PDF once it has been processed
    // (a turn can only search a document that has finished ingestion, so this waits for it).
    let referenced: MentionableDocument[] = extras?.documents ?? []
    if (extras?.pdf) {
      const { file, documentType } = extras.pdf
      const controller = new AbortController()
      uploadAbortRef.current = controller
      try {
        setPdfUpload({ filename: file.name, phase: "uploading" })
        const uploaded = await uploadDocument({ file, document_type: documentType })
        setPdfUpload({ filename: file.name, phase: "extracting" })
        const ready = await waitForDocumentReady(uploaded.id, { signal: controller.signal })
        void queryClient.invalidateQueries({ queryKey: documentKeys.all })
        referenced = [
          ...referenced.filter((d) => d.id !== ready.id),
          { id: ready.id, filename: ready.filename, document_type: ready.document_type },
        ]
      } catch (err) {
        if (epoch === epochRef.current) {
          setError(
            `Couldn't add ${file.name}: ${isApiError(err) && "message" in err ? err.message : err instanceof Error ? err.message : "something went wrong."}`
          )
        }
        return false
      } finally {
        if (epoch === epochRef.current) setPdfUpload(null)
      }
      if (epoch !== epochRef.current) return false
    }

    let attachmentUrl: string | undefined
    if (image) {
      try {
        attachmentUrl = await uploadImage(image)
      } catch (err) {
        if (epoch === epochRef.current) {
          setError(isApiError(err) && "message" in err ? `Couldn't upload the photo: ${err.message}` : "Couldn't upload the photo.")
        }
        return false
      }
      if (epoch !== epochRef.current) return false
    }

    // An attached PDF is named in the text, like a mention, so the transcript shows what the question was about.
    const pdfName = extras?.pdf?.file.name
    const base = typed || (extras?.pdf ? PDF_ONLY_MESSAGE : IMAGE_ONLY_MESSAGE)
    const text = pdfName && !base.includes(`@${pdfName}`) ? `${base} @${pdfName}` : base
    const documentIds = referenced.map((d) => d.id)
    const userId = newId()
    const assistantId = newId()
    setMessages((prev) => [
      ...prev,
      {
        id: userId,
        role: "user",
        text,
        ...(attachmentUrl ? { imageUrl: attachmentUrl } : {}),
        ...(referenced.length > 0 ? { documents: referenced.map((d) => ({ id: d.id, filename: d.filename })) } : {}),
      },
      { id: assistantId, role: "assistant", text: "" },
    ])
    setIsStreaming(true)
    const controller = new AbortController()
    abortRef.current = controller

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
        return false
      }
      if (epoch !== epochRef.current) return false // the user opened another chat meanwhile
      heldRef.current = sid
      setSessionId(sid)
      router.replace(`/chat?session=${sid}`)
    }

    const streamSessionId = sid
    void (async () => {
      try {
        const events =
          documentIds.length > 0
            ? sendChatMessage(streamSessionId, text, controller.signal, attachmentUrl, documentIds)
            : sendChatMessage(streamSessionId, text, controller.signal, attachmentUrl)
        await consume(events, assistantId, epoch)
      } catch (err) {
        if (epoch !== epochRef.current) return
        setIsStreaming(false)
        setError(isApiError(err) && "message" in err ? err.message : "Couldn't reach the AI assistant.")
        refreshSessions()
      }
    })()
    return true
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

  function handleDelete(id: string) {
    const title = sessionsQuery.data?.find((s) => s.id === id)?.title ?? "this conversation"
    if (!window.confirm(`Delete "${title}"? This permanently removes the conversation and its messages.`)) return
    deleteMutation.mutate(id, {
      onSuccess: () => {
        // Deleting the conversation on screen: back to a fresh "New chat", with the gone id out of the URL.
        if (id === heldRef.current) {
          resetConversation()
          heldRef.current = null
          setSessionId(null)
          router.replace("/chat")
        }
      },
      onError: () => toast.error("Couldn't delete this conversation."),
    })
  }

  function handleRename(id: string, title: string) {
    renameMutation.mutate(
      { id, title },
      { onError: () => toast.error("Couldn't rename this conversation.") }
    )
  }

  const onSend = useStableCallback(handleSend)
  const onStop = useStableCallback(handleStop)
  const onNew = useStableCallback(handleNewChat)
  const onSelect = useStableCallback(handleSelect)
  const onRename = useStableCallback(handleRename)
  const onDelete = useStableCallback(handleDelete)
  const onRetrySessions = useStableCallback(() => void sessionsQuery.refetch())

  const activeTitle = sessionsQuery.data?.find((s) => s.id === sessionId)?.title ?? "New chat"
  const composerBlocked = history.status !== "idle"

  const sidebar = (
    <ChatSessionSidebar
      sessions={sessionsQuery.data}
      isPending={sessionsQuery.isPending}
      isError={sessionsQuery.isError}
      onRetry={onRetrySessions}
      activeId={sessionId}
      onSelect={onSelect}
      onNew={onNew}
      onRename={onRename}
      onDelete={onDelete}
    />
  )

  return (
    // Fills the viewport below the topbar exactly, so the page itself never scrolls and the
    // composer is pinned flush to the bottom edge. Height = 100dvh minus the shell's top padding
    // (1rem), the topbar (--topbar-height, fixed in globals.css) and the gap under it (1rem);
    // -mb-4 then reaches down through the shell's 1rem bottom padding, so there is no strip of
    // background under the input. dvh, not vh: on mobile, vh includes the area under the
    // browser's address bar.
    <div className="-mb-4 flex h-[calc(100dvh-2rem-var(--topbar-height))] min-h-0 gap-4 overflow-hidden">
      <PageHeader crumbs={[{ label: "AI Assistant" }]} />

      <aside aria-label="Conversations" className="hidden w-72 shrink-0 pb-4 md:flex">
        {sidebar}
      </aside>

      <section aria-label="Chat" data-testid="chat-section" className="flex min-h-0 min-w-0 flex-1 flex-col">
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
              {pdfUpload ? <DocumentUploadCard filename={pdfUpload.filename} phase={pdfUpload.phase} /> : null}
              {isStreaming && activity.length > 0 ? <AgentActivity steps={activity} /> : null}
              {hitlState ? (
                <Suspense fallback={<Skeleton className="h-28 w-full" aria-label="Loading approval" />}>
                  <ApprovalCard
                    hitlState={hitlState}
                    onApprove={() => void handleApprovalDecision("approve")}
                    onModify={(notes) => void handleApprovalDecision("modify", { notes })}
                    onReject={() => void handleApprovalDecision("reject")}
                  />
                </Suspense>
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
          onSend={onSend}
          onStop={onStop}
          isStreaming={isStreaming}
          disabled={isStreaming || Boolean(hitlState) || composerBlocked}
          disabledReason={hitlState ? "Waiting on your approval above…" : undefined}
          documents={mentionable}
          pdfTypes={pdfTypes}
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
