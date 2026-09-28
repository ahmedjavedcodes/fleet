import { RoutePlaceholder } from "@/components/states/route-placeholder"

export default function DriverDetailPage() {
  return (
    <RoutePlaceholder
      title="Driver detail"
      crumbs={[{ label: "Drivers", href: "/foundation/drivers" }, { label: "Driver detail" }]}
    />
  )
}
