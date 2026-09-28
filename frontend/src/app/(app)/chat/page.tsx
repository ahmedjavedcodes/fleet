import { PageHeader } from "@/components/layout/page-header"
import { NotAvailableYet } from "@/components/states/not-available-yet"

export default function ChatPage() {
  return (
    <>
      <PageHeader crumbs={[{ label: "AI Assistant" }]} />
      <NotAvailableYet feature="The AI Assistant" />
    </>
  )
}
