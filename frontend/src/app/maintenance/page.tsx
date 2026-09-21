import { Wrench } from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";

// TODO(Spec 02/03): wire up against backend/app/api/maintenance.py,
// inventory.py, purchase_orders.py, compliance.py — mechanic logs, parts
// stock levels, and the manufacturer-guideline compliance matrix.
export default function MaintenancePage() {
  return (
    <main className="min-h-screen p-8">
      <div className="flex items-center gap-2">
        <Wrench className="h-6 w-6" />
        <h1 className="text-2xl font-semibold">Maintenance & Parts</h1>
      </div>
      <p className="mt-2 text-sm text-neutral-500">Mechanic logs, parts inventory, and manufacturer compliance tracking.</p>

      <div className="mt-8">
        <EmptyState
          title="No maintenance records yet"
          description="Log a service entry or import parts inventory to see the maintenance calendar and low-stock alerts."
        />
      </div>
    </main>
  );
}
