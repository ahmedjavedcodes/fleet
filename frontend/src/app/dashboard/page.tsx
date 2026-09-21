import { AlertTriangle, Fuel, ShieldAlert, Truck, Users, Wrench } from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";
import { apiFetch, ApiError } from "@/lib/api-client";
import { getServerToken } from "@/lib/auth-server";
import type { DashboardSummaryResponse, FuelTrendsResponse } from "@/lib/types/dashboard";

import { FuelTrendChart } from "./FuelTrendChart";

async function loadDashboard(token: string | null) {
  const [summary, fuelTrends] = await Promise.all([
    apiFetch<DashboardSummaryResponse>("/api/v1/dashboard/summary", { token }),
    apiFetch<FuelTrendsResponse>("/api/v1/dashboard/fuel-trends", { token }),
  ]);
  return { summary, fuelTrends };
}

export default async function DashboardPage() {
  const token = await getServerToken();

  let data: Awaited<ReturnType<typeof loadDashboard>> | null = null;
  let forbidden = false;

  try {
    data = await loadDashboard(token);
  } catch (err) {
    if (err instanceof ApiError && err.kind === "forbidden") {
      forbidden = true;
    } else {
      // Anything else (network, 500, unauthorized) bubbles to error.tsx,
      // which offers a retry — a permission error never should.
      throw err;
    }
  }

  if (forbidden) {
    return (
      <main className="min-h-screen p-8">
        <EmptyState
          icon={ShieldAlert}
          title="You don't have access to fleet insights"
          description="Executive dashboard data is limited to admins and fleet managers. Contact your organization admin if you believe this is a mistake."
        />
      </main>
    );
  }

  const { summary, fuelTrends } = data!;

  return (
    <main className="min-h-screen p-8">
      <div className="flex items-center gap-2">
        <Truck className="h-6 w-6" />
        <h1 className="text-2xl font-semibold">Fleet Dashboard</h1>
      </div>
      <p className="mt-2 text-sm text-neutral-500">Executive fleet insights, derived from manual logs and uploaded records.</p>

      <div className="mt-8 grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        <StatCard icon={Truck} label="Vehicles" value={summary.total_vehicles} />
        <StatCard icon={Users} label="Active drivers" value={summary.active_drivers} />
        <StatCard icon={Fuel} label="Fuel cost (mo)" value={`$${summary.month_fuel_cost.toFixed(2)}`} />
        <StatCard icon={Wrench} label="Overdue maintenance" value={summary.overdue_maintenance_count} warn={summary.overdue_maintenance_count > 0} />
        <StatCard icon={AlertTriangle} label="Open incidents" value={summary.open_incidents_count} warn={summary.open_incidents_count > 0} />
        <StatCard icon={AlertTriangle} label="Low stock parts" value={summary.low_stock_parts_count} warn={summary.low_stock_parts_count > 0} />
      </div>

      <section className="mt-8">
        <h2 className="text-sm font-medium text-neutral-700 dark:text-neutral-300">Fuel cost trend</h2>
        <div className="mt-3 h-64 w-full">
          {fuelTrends.length === 0 ? (
            <EmptyState icon={Fuel} title="No fuel logs yet" description="Fuel cost trends appear once fuel receipts or manual logs are recorded." />
          ) : (
            <FuelTrendChart data={fuelTrends} />
          )}
        </div>
      </section>
    </main>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  warn = false,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string | number;
  warn?: boolean;
}) {
  return (
    <div className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
      <Icon className={`h-4 w-4 ${warn ? "text-amber-600" : "text-neutral-400"}`} />
      <p className="mt-2 text-xl font-semibold">{value}</p>
      <p className="text-xs text-neutral-500">{label}</p>
    </div>
  );
}
