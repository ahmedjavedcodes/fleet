import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { DriverTimelineItem } from "@/app/(app)/foundation/drivers/[id]/_components/driver-timeline-item"
import type { TimelineEntry } from "@/lib/schemas/timeline"

const VEHICLE = {
  vehicle_id: "11111111-1111-4111-8111-111111111111",
  vehicle_plate: "LEA-1001",
  vehicle_name: "Toyota Hilux",
  driver_id: "22222222-2222-4222-8222-222222222222",
}

const trip: TimelineEntry = {
  record_type: "trip",
  id: "99999999-9999-4999-8999-999999999999",
  date: "2026-06-12T08:00:00Z",
  summary: {
    ...VEHICLE,
    start_time: "2026-06-12T08:00:00Z",
    end_time: "2026-06-12T10:00:00Z",
    start_odometer: 45000,
    end_odometer: 45250,
    distance_km: 250,
    fuel_consumed: null,
    notes: null,
  },
}

const report: TimelineEntry = {
  record_type: "report",
  id: "77777777-7777-4777-8777-777777777777",
  date: "2026-06-14T00:00:00Z",
  summary: {
    ...VEHICLE,
    odometer: 45250,
    shift_date: "2026-06-14",
    vehicle_condition: "good",
    handover_notes: null,
    issues_reported: null,
  },
}

const incident: TimelineEntry = {
  record_type: "incident",
  id: "88888888-8888-4888-8888-888888888888",
  date: "2026-06-13T00:00:00Z",
  summary: {
    ...VEHICLE,
    odometer: null,
    driver_id: VEHICLE.driver_id,
    incident_type: "damage",
    date: "2026-06-13",
    severity: "minor",
    description: "Scratch",
    location_description: null,
    estimated_cost: null,
    resolution_status: "open",
    resolution_notes: null,
  },
}

describe("DriverTimelineItem", () => {
  it("links the vehicle plate next to the event type for every record type", () => {
    for (const [entry, label] of [[trip, "Trip"], [report, "Report"], [incident, "Incident"]] as const) {
      const { unmount } = render(<DriverTimelineItem entry={entry} />)
      expect(screen.getByText(new RegExp(`· ${label}$`))).toBeInTheDocument()
      expect(screen.getByRole("link", { name: "LEA-1001" })).toHaveAttribute("href", `/foundation/vehicles/${VEHICLE.vehicle_id}`)
      expect(screen.getByText("Toyota Hilux")).toBeInTheDocument()
      unmount()
    }
  })

  it("shows the start → end odometer range for a trip", () => {
    render(<DriverTimelineItem entry={trip} />)
    expect(screen.getByText("Odometer: 45,000 → 45,250")).toBeInTheDocument()
  })

  it("shows a single odometer snapshot for a report", () => {
    render(<DriverTimelineItem entry={report} />)
    expect(screen.getByText("Odometer: 45,250")).toBeInTheDocument()
  })

  it("omits the odometer line when no snapshot is available", () => {
    render(<DriverTimelineItem entry={incident} />)
    expect(screen.queryByText(/Odometer/)).not.toBeInTheDocument()
  })
})
