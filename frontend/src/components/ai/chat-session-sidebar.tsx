"use client"

import { MessageSquare, Pencil, Plus } from "lucide-react"
import { useRef, useState } from "react"
import { formatDate } from "@/lib/format-date"
import type { ChatSessionSummary } from "@/lib/schemas/chat"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"

// The conversation list beside the chat: a prominent "New chat" button on top, then the
// user's past conversations (newest activity first) in a scrollable list. The active one is
// highlighted; the pencil turns a title into an input (Enter or leaving the field saves,
// Escape cancels). Purely presentational: the page owns the data and every action.
export function ChatSessionSidebar({
  sessions,
  isPending,
  isError,
  onRetry,
  activeId,
  onSelect,
  onNew,
  onRename,
}: {
  sessions: ChatSessionSummary[] | undefined
  isPending: boolean
  isError: boolean
  onRetry: () => void
  activeId: string | null
  onSelect: (id: string) => void
  onNew: () => void
  onRename: (id: string, title: string) => void
}) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState("")
  // Enter saves and then the field unmounts, which can also fire blur; save once.
  const settled = useRef(false)

  function startEditing(session: ChatSessionSummary) {
    settled.current = false
    setDraft(session.title)
    setEditingId(session.id)
  }

  function finishEditing(session: ChatSessionSummary, save: boolean) {
    if (settled.current) return
    settled.current = true
    const title = draft.trim()
    setEditingId(null)
    if (save && title !== "" && title !== session.title) onRename(session.id, title)
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col rounded-xl border border-border bg-card">
      <div className="p-3">
        <Button className="w-full" onClick={onNew}>
          <Plus className="size-4" />
          New chat
        </Button>
      </div>

      <nav aria-label="Chat history" className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {isPending ? (
          <div className="space-y-2 p-1" aria-busy="true" aria-label="Loading conversations">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-11 w-full" />
            ))}
          </div>
        ) : isError ? (
          <div role="alert" className="space-y-2 p-3 text-sm">
            <p className="text-foreground">Couldn&apos;t load your conversations.</p>
            <Button variant="outline" size="sm" onClick={onRetry}>
              Try again
            </Button>
          </div>
        ) : !sessions || sessions.length === 0 ? (
          <div className="flex flex-col items-center gap-2 p-6 text-center">
            <MessageSquare className="size-5 text-muted-foreground" aria-hidden />
            <p className="text-sm font-medium text-foreground">No conversations yet</p>
            <p className="text-caption text-muted-foreground">Send a message to start one. It will appear here.</p>
          </div>
        ) : (
          <ul className="space-y-1">
            {sessions.map((session) => {
              const active = session.id === activeId
              return (
                <li key={session.id} className="group relative">
                  {editingId === session.id ? (
                    <form
                      className="p-1"
                      onSubmit={(e) => {
                        e.preventDefault()
                        finishEditing(session, true)
                      }}
                    >
                      <Input
                        autoFocus
                        aria-label={`Rename ${session.title}`}
                        value={draft}
                        maxLength={200}
                        onChange={(e) => setDraft(e.target.value)}
                        onBlur={() => finishEditing(session, true)}
                        onKeyDown={(e) => {
                          if (e.key === "Escape") {
                            e.preventDefault()
                            finishEditing(session, false)
                          }
                        }}
                        className="h-9"
                      />
                    </form>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => onSelect(session.id)}
                        aria-current={active ? "true" : undefined}
                        className={cn(
                          "flex w-full cursor-pointer flex-col rounded-lg px-3 py-2 pr-10 text-left transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                          active && "bg-muted"
                        )}
                      >
                        <span className={cn("truncate text-sm text-foreground", active ? "font-semibold" : "font-medium")}>{session.title}</span>
                        <span className="text-caption text-muted-foreground">{formatDate(session.updated_at.slice(0, 10))}</span>
                      </button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Rename ${session.title}`}
                        onClick={() => startEditing(session)}
                        className="absolute top-1/2 right-1 -translate-y-1/2 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 max-md:opacity-100"
                      >
                        <Pencil className="size-3.5" />
                      </Button>
                    </>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </nav>
    </div>
  )
}
