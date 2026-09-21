import { Truck } from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";

// TODO(Spec 00): wire up against backend/app/api/vehicles.py, drivers.py,
// suppliers.py for entity CRUD, and expose the Fleet Registry Agent
// (ai_agents/agents/foundation) over a backend route once one exists —
// currently it only has a local test console (backend/seed_test_users.py
// era), no HTTP endpoint to call from here yet.
export default function RegistryPage() {
  return (
    <main className="min-h-screen p-8">
      <div className="flex items-center gap-2">
        <Truck className="h-6 w-6" />
        <h1 className="text-2xl font-semibold">Fleet Registry</h1>
      </div>
      <p className="mt-2 text-sm text-neutral-500">Vehicles, drivers, and suppliers — onboarded manually or via the Fleet Registry Agent.</p>

      <div className="mt-8">
        <EmptyState
          title="Registry UI not wired up yet"
          description="Entity tables (vehicles, drivers, suppliers) and the Fleet Registry Agent chat panel land here. Backend CRUD endpoints already exist under /api/v1/vehicles, /drivers, /suppliers."
        />
      </div>
    </main>
  );
}
