"use client"

import { AlertTriangle, BellRing } from "lucide-react"
import { useMarkNotificationRead, useNotifications } from "@/lib/api/notifications"
import type { Notification } from "@/lib/schemas/notification"
import { PageHeader } from "@/components/layout/page-header"
import { NotificationItem } from "@/components/notifications/notification-item"
import { EmptyState } from "@/components/states/empty-state"
import { NotAvailableYet } from "@/components/states/not-available-yet"
import { PageSkeleton } from "@/components/states/page-skeleton"
import { QueryRegion } from "@/components/states/query-boundary"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

function unreadCount(rows: Notification[] | undefined, type: Notification["type"]): number {
  return rows?.filter((n) => n.type === type && !n.is_read).length ?? 0
}

function TabLabel({ label, count }: { label: string; count: number }) {
  return (
    <>
      {label}
      {count > 0 ? (
        <span className="ml-1.5 rounded-full bg-info-soft px-1.5 text-caption font-medium text-info-strong" aria-label={`${count} unread`}>
          {count}
        </span>
      ) : null}
    </>
  )
}

export default function NotificationsPage() {
  const notificationsQuery = useNotifications()
  const markRead = useMarkNotificationRead()

  function open(notification: Notification) {
    if (!notification.is_read) markRead.mutate(notification.id)
  }

  function list(rows: Notification[], type: Notification["type"], empty: React.ReactNode) {
    const ofType = rows.filter((n) => n.type === type)
    if (ofType.length === 0) return empty
    return (
      <ul className="space-y-2">
        {ofType.map((n) => (
          <li key={n.id}>
            <NotificationItem notification={n} onOpen={open} />
          </li>
        ))}
      </ul>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader crumbs={[{ label: "Notifications" }]} />
      <Tabs defaultValue="warnings">
        <TabsList>
          <TabsTrigger value="warnings">
            <TabLabel label="Warnings" count={unreadCount(notificationsQuery.data, "warning")} />
          </TabsTrigger>
          <TabsTrigger value="events">
            <TabLabel label="Notified events" count={unreadCount(notificationsQuery.data, "event")} />
          </TabsTrigger>
          <TabsTrigger value="triggers">Triggers</TabsTrigger>
        </TabsList>

        <TabsContent value="warnings">
          <QueryRegion query={notificationsQuery} skeleton={<PageSkeleton />} areaLabel="notifications">
            {(rows) =>
              list(
                rows,
                "warning",
                <EmptyState icon={AlertTriangle} title="No warnings" description="Serious incidents and alerts will show up here." />
              )
            }
          </QueryRegion>
        </TabsContent>

        <TabsContent value="events">
          <QueryRegion query={notificationsQuery} skeleton={<PageSkeleton />} areaLabel="notifications">
            {(rows) =>
              list(
                rows,
                "event",
                <EmptyState icon={BellRing} title="No notified events" description="Reported incidents and other updates will show up here." />
              )
            }
          </QueryRegion>
        </TabsContent>

        <TabsContent value="triggers">
          <NotAvailableYet feature="Triggers" />
        </TabsContent>
      </Tabs>
    </div>
  )
}
