"use client"

import Link from "next/link"
import { formatDateTime } from "@/lib/format-date"
import type { Notification } from "@/lib/schemas/notification"
import { cn } from "@/lib/utils"

// One notification row. Unread ones carry a blue dot and a bold title; clicking
// (or pressing Enter/Space) reports it via onOpen so the caller can mark it read.
// Read rows stay buttons for a consistent tab order, and simply do nothing new.
// An entry derived from an open incident has no read state to change: it is a
// link to where incidents are handled instead.
export function NotificationItem({
  notification,
  onOpen,
  compact = false,
}: {
  notification: Notification
  onOpen: (notification: Notification) => void
  compact?: boolean
}) {
  const unread = !notification.is_read
  const className = cn(
    "flex w-full cursor-pointer items-start gap-3 rounded-lg border border-border bg-card px-3 py-2.5 text-left transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
    compact && "border-0 px-2 py-2"
  )
  const content = (
    <>
      <span className="mt-1.5 flex size-2 shrink-0 items-center justify-center">
        {unread ? <span data-testid="unread-dot" role="img" aria-label="Unread" className="size-2 rounded-full bg-info" /> : null}
      </span>
      <span className="min-w-0 flex-1">
        <span className={cn("block text-sm text-foreground", unread ? "font-semibold" : "font-medium")}>{notification.title}</span>
        <span className={cn("mt-0.5 block text-caption text-muted-foreground", compact && "line-clamp-2")}>{notification.message}</span>
        <span className="mt-1 block text-caption text-muted-foreground">{formatDateTime(notification.created_at)}</span>
      </span>
    </>
  )

  if (notification.source === "incident") {
    return (
      <Link href="/accountability" className={className} data-testid="incident-notification">
        {content}
      </Link>
    )
  }
  return (
    <button type="button" onClick={() => onOpen(notification)} className={className}>
      {content}
    </button>
  )
}
