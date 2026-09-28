import { RoutePlaceholder } from "@/components/states/route-placeholder"

export default function VehicleDetailPage() {
  return (
    <RoutePlaceholder
      title="Vehicle detail"
      crumbs={[{ label: "Vehicles", href: "/foundation/vehicles" }, { label: "Vehicle detail" }]}
    />
  )
}
