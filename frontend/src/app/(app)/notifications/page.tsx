import { PageHeader } from "@/components/layout/page-header"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { NotAvailableYet } from "@/components/states/not-available-yet"

// AlertDispatcher only logs — no notifications API exists (CLAUDE.md §5.5,
// lib/api/notifications.ts). All three tabs are NotAvailableYet; the bell
// never shows a count (plans/03).
export default function NotificationsPage() {
  return (
    <div className="space-y-6">
      <PageHeader crumbs={[{ label: "Notifications" }]} />
      <Tabs defaultValue="warnings">
        <TabsList>
          <TabsTrigger value="warnings">Warnings</TabsTrigger>
          <TabsTrigger value="events">Notified events</TabsTrigger>
          <TabsTrigger value="triggers">Triggers</TabsTrigger>
        </TabsList>
        <TabsContent value="warnings">
          <NotAvailableYet feature="Warnings" />
        </TabsContent>
        <TabsContent value="events">
          <NotAvailableYet feature="Notified events" />
        </TabsContent>
        <TabsContent value="triggers">
          <NotAvailableYet feature="Triggers" />
        </TabsContent>
      </Tabs>
    </div>
  )
}
