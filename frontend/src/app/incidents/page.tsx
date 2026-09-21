import { AlertTriangle } from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";

// TODO(Spec 04): wire up against backend/app/api/incidents.py,
// driver_reports.py, and app/schemas/accountability.py's TimelineResponse
// for the per-driver auditable trail.
export default function IncidentsPage() {
  return (
    <main className="min-h-screen p-8">
      <div className="flex items-center gap-2">
        <AlertTriangle className="h-6 w-6" />
        <h1 className="text-2xl font-semibold">Incidents & Driver Timelines</h1>
      </div>
      <p className="mt-2 text-sm text-neutral-500">Digitized driver reports, incident logs, and accountability timelines.</p>

      <div className="mt-8">
        <EmptyState
          title="No incidents reported"
          description="Reported incidents and their resolution status will appear here, alongside each driver's timeline."
        />
      </div>
    </main>
  );
}
