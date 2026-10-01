"use client"

import { AlertTriangle, BellRing } from "lucide-react"
import { useNotificationPages } from "@/lib/api/notifications"
import type { Notification } from "@/lib/schemas/notification"
import { PageHeader } from "@/components/layout/page-header"
import { NotificationItem } from "@/components/notifications/notification-item"
import { useOpenNotification } from "@/components/notifications/use-open-notification"
import { EmptyState } from "@/components/states/empty-state"
import { PageSkeleton } from "@/components/states/page-skeleton"
import { QueryRegion } from "@/components/states/query-boundary"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

function unreadCount(rows: Notification[] | undefined): number {
  return rows?.filter((n) => !n.is_read).length ?? 0
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

type FeedQuery = ReturnType<typeof useNotificationPages>

// One tab: the notifications of one type, a page at a time. Only what has been loaded is rendered, however many
// incidents there are.
function Feed({
  query,
  empty,
  onOpen,
}: {
  query: FeedQuery
  empty: React.ReactNode
  onOpen: (notification: Notification) => void
}) {
  return (
    <QueryRegion query={query} skeleton={<PageSkeleton />} isEmpty={(rows) => rows.length === 0} empty={empty} areaLabel="notifications">
      {(rows) => (
        <div className="space-y-3">
          <ul className="space-y-2">
            {rows.map((n) => (
              <li key={n.id}>
                <NotificationItem notification={n} onOpen={onOpen} />
              </li>
            ))}
          </ul>
          {query.hasNextPage ? (
            <div className="flex justify-center">
              <Button type="button" variant="outline" disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>
                {query.isFetchingNextPage ? "Loading…" : "Load more"}
              </Button>
            </div>
          ) : null}
        </div>
      )}
    </QueryRegion>
  )
}

export default function NotificationsPage() {
  const warningsQuery = useNotificationPages("warning")
  const eventsQuery = useNotificationPages("event")
  const open = useOpenNotification()

  return (
    <div className="space-y-6">
      <PageHeader crumbs={[{ label: "Notifications" }]} />
      <Tabs defaultValue="warnings">
        <TabsList>
          <TabsTrigger value="warnings">
            <TabLabel label="Warnings" count={unreadCount(warningsQuery.data)} />
          </TabsTrigger>
          <TabsTrigger value="events">
            <TabLabel label="Notified events" count={unreadCount(eventsQuery.data)} />
          </TabsTrigger>
        </TabsList>

        <TabsContent value="warnings">
          <Feed
            query={warningsQuery}
            onOpen={open}
            empty={<EmptyState icon={AlertTriangle} title="No warnings" description="Serious incidents and alerts will show up here." />}
          />
        </TabsContent>

        <TabsContent value="events">
          <Feed
            query={eventsQuery}
            onOpen={open}
            empty={<EmptyState icon={BellRing} title="No notified events" description="Reported incidents and other updates will show up here." />}
          />
        </TabsContent>
      </Tabs>
    </div>
  )
}
