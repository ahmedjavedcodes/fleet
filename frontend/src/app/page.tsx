import { Truck } from "lucide-react";

import { DeliveriesChart } from "@/components/DeliveriesChart";

const placeholderData = [
  { month: "Jan", deliveries: 32 },
  { month: "Feb", deliveries: 41 },
  { month: "Mar", deliveries: 38 },
];

export default function DashboardPage() {
  return (
    <main className="min-h-screen p-8">
      <div className="flex items-center gap-2">
        <Truck className="h-6 w-6" />
        <h1 className="text-2xl font-semibold">Fleet Dashboard</h1>
      </div>
      <p className="mt-2 text-sm text-neutral-500">
        Scaffold placeholder, wired to Tailwind CSS, Lucide Icons, and Recharts.
      </p>
      <div className="mt-8 h-64 w-full max-w-xl">
        <DeliveriesChart data={placeholderData} />
      </div>
    </main>
  );
}
