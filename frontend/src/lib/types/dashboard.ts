// Mirrors backend/app/schemas/dashboard.py. Decimal fields (money, ratios)
// arrive as JSON strings-or-numbers over the wire — Pydantic's Decimal
// serializes to a plain number in the response body, so `number` is correct
// here even though the backend type is Decimal.
import type { ServiceType } from "./enums";

export interface DashboardSummaryResponse {
  total_vehicles: number;
  active_drivers: number;
  month_fuel_cost: number;
  overdue_maintenance_count: number;
  low_stock_parts_count: number;
  open_incidents_count: number;
}

export interface FuelTrendPoint {
  month: string;
  total_cost: number;
  avg_cost_per_km: number | null;
}

export type FuelTrendsResponse = FuelTrendPoint[];

export interface MaintenanceCalendarItem {
  vehicle_id: string;
  plate_number: string;
  service_type: ServiceType;
  // Nullable: an item overdue purely by km (no service_interval_months
  // configured) has no next_due_date — it still appears, never dropped.
  due_date: string | null;
  due_km: number | null;
  status: "upcoming" | "overdue";
}

export type MaintenanceCalendarResponse = MaintenanceCalendarItem[];

export interface VehicleHealthSignals {
  compliance: number | null;
  incidents: number | null;
  maintenance_currency: number | null;
  fuel_efficiency: number | null;
}

export interface VehicleHealthScore {
  vehicle_id: string;
  plate_number: string;
  health_score: number;
  signals: VehicleHealthSignals;
}

export type FleetHealthResponse = VehicleHealthScore[];
