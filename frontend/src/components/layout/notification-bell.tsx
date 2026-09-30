"use client"

import { Bell } from "lucide-react"
import Link from "next/link"
import { useMarkNotificationRead, useNotifications } from "@/lib/api/notifications"
import type { Notification } from "@/lib/schemas/notification"
import { NotificationItem } from "@/components/notifications/notification-item"
import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"

const PREVIEW_COUNT = 5

// A small blue dot (never a count) when anything is unread, and the latest few
// notifications in the popover. Clicking one marks it read.
export function NotificationBell() {
  const query = useNotifications()
  const markRead = useMarkNotificationRead()
  const rows = query.data ?? []
  const hasUnread = rows.some((n) => !n.is_read)

  function open(notification: Notification) {
    if (!notification.is_read) markRead.mutate(notification.id)
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label={hasUnread ? "Notifications (unread)" : "Notifications"}
          className="relative"
        >
          <Bell aria-hidden />
          {hasUnread ? <span data-testid="bell-unread-dot" className="absolute top-1.5 right-1.5 size-2 rounded-full bg-info" /> : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-2">
        {query.isError ? (
          <p className="px-2 py-3 text-caption text-muted-foreground">Couldn&apos;t load notifications.</p>
        ) : rows.length === 0 ? (
          <p className="px-2 py-3 text-caption text-muted-foreground">{query.isPending ? "Loading…" : "You're all caught up."}</p>
        ) : (
          <ul className="space-y-1">
            {rows.slice(0, PREVIEW_COUNT).map((n) => (
              <li key={n.id}>
                <NotificationItem notification={n} onOpen={open} compact />
              </li>
            ))}
          </ul>
        )}
        <Link href="/notifications" className="mt-2 block px-2 pb-1 text-sm font-medium text-primary-strong hover:underline">
          Go to Notifications
        </Link>
      </PopoverContent>
    </Popover>
  )
}
