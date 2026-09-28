import { useQuery } from "@tanstack/react-query"
import { dashboardKeys } from "@/lib/query/keys"
import {
  dashboardSummaryResponseSchema,
  fleetHealthResponseSchema,
  fuelTrendsResponseSchema,
  maintenanceCalendarResponseSchema,
  type DashboardSummaryResponse,
  type FleetHealthResponse,
  type FuelTrendsResponse,
  type MaintenanceCalendarResponse,
} from "@/lib/schemas/dashboard"
import { apiRequest } from "./client"

// Every endpoint here is Admin/Fleet-Manager only (CLAUDE.md §2.2) — never
// call these for M/D; compose their dashboards from the endpoints those
// roles can actually read instead (plans/04).

export function getDashboardSummary(): Promise<DashboardSummaryResponse> {
  return apiRequest("/dashboard/summary", { schema: dashboardSummaryResponseSchema })
}

export function getFuelTrends(months?: number): Promise<FuelTrendsResponse> {
  return apiRequest("/dashboard/fuel-trends", { query: { months }, schema: fuelTrendsResponseSchema })
}

export function getMaintenanceCalendar(windowDays?: number): Promise<MaintenanceCalendarResponse> {
  return apiRequest("/dashboard/maintenance-calendar", {
    query: { window_days: windowDays },
    schema: maintenanceCalendarResponseSchema,
  })
}

export function getFleetHealth(): Promise<FleetHealthResponse> {
  return apiRequest("/dashboard/fleet-health", { schema: fleetHealthResponseSchema })
}

export function useDashboardSummary() {
  return useQuery({ queryKey: dashboardKeys.summary(), queryFn: getDashboardSummary })
}

export function useFuelTrends(months?: number) {
  return useQuery({ queryKey: dashboardKeys.fuelTrends(months), queryFn: () => getFuelTrends(months) })
}

export function useMaintenanceCalendar(windowDays?: number) {
  return useQuery({
    queryKey: dashboardKeys.maintenanceCalendar(windowDays),
    queryFn: () => getMaintenanceCalendar(windowDays),
  })
}

export function useFleetHealth() {
  return useQuery({ queryKey: dashboardKeys.fleetHealth(), queryFn: getFleetHealth })
}
