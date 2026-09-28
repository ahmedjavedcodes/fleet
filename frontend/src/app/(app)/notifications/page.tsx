import { PageHeader } from "@/components/layout/page-header"
import { NotAvailableYet } from "@/components/states/not-available-yet"

export default function NotificationsPage() {
  return (
    <>
      <PageHeader crumbs={[{ label: "Notifications" }]} />
      <NotAvailableYet feature="Notifications" />
    </>
  )
}
