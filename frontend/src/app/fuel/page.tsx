import { Fuel } from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";

// TODO(Spec 01): wire up against backend/app/api/fuel.py — fuel log CRUD,
// receipt upload (multipart, .jpg/.png), and leakage-auditor results.
export default function FuelPage() {
  return (
    <main className="min-h-screen p-8">
      <div className="flex items-center gap-2">
        <Fuel className="h-6 w-6" />
        <h1 className="text-2xl font-semibold">Fuel Logs</h1>
      </div>
      <p className="mt-2 text-sm text-neutral-500">Manual fuel entries, uploaded receipts, and leakage-auditor findings.</p>

      <div className="mt-8">
        <EmptyState
          title="No fuel logs yet"
          description="Add your first fuel entry or upload a receipt to start tracking cost per km and flag anomalies."
        />
      </div>
    </main>
  );
}
