import Link from "next/link"

// The vehicle's plate number as a link to its detail page. Tables use this
// instead of a generic "View vehicle" label. `name` (e.g. "Toyota Hilux") is an
// optional muted second line. With no plate there is nothing meaningful to
// show, so it renders a dash rather than an empty link.
export function VehicleLink({
  vehicleId,
  plate,
  name,
}: {
  vehicleId: string
  plate: string | null | undefined
  name?: string | null
}) {
  if (!plate) return <span className="text-muted-foreground">—</span>
  return (
    <div>
      <Link href={`/foundation/vehicles/${vehicleId}`} className="font-medium text-foreground hover:underline">
        {plate}
      </Link>
      {name ? <p className="text-caption text-muted-foreground">{name}</p> : null}
    </div>
  )
}
