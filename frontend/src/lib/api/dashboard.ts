import { useInfiniteQuery, useQuery } from "@tanstack/react-query"
import { z } from "zod"
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
  type MaintenanceCalendarItem,
  type VehicleHealthScore,
} from "@/lib/schemas/dashboard"
import { apiRequest, apiRequestPage, type Page } from "./client"
import { nextOffset } from "./paging"

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

// How many rows the dashboard's lists fetch (and render) at a time; "Load more" fetches the next page.
export const DASHBOARD_PAGE_SIZE = 25

/** A list that loads page by page: everything fetched so far, and the unpaged total when the backend reports it. */
export type PagedList<T> = { items: T[]; total: number | null }

function toPagedList<T>(data: { pages: Page<T[]>[] }): PagedList<T> {
  return { items: data.pages.flatMap((p) => p.items), total: data.pages[0]?.total ?? null }
}

/** Fleet-health filters, applied by the backend before paging: search is plate/make/model; health is a 0-100 range. */
export type FleetHealthFilters = {
  search?: string
  healthMin?: number
  healthMax?: number
  make?: string
  status?: string
}

export function getMaintenanceCalendarPage(windowDays: number, offset: number, search?: string): Promise<Page<MaintenanceCalendarResponse>> {
  return apiRequestPage("/dashboard/maintenance-calendar", {
    query: { window_days: windowDays, limit: DASHBOARD_PAGE_SIZE, offset, search: search || undefined },
    schema: maintenanceCalendarResponseSchema,
  })
}

export function getFleetHealthPage(offset: number, filters: FleetHealthFilters = {}): Promise<Page<FleetHealthResponse>> {
  return apiRequestPage("/dashboard/fleet-health", {
    query: {
      limit: DASHBOARD_PAGE_SIZE,
      offset,
      search: filters.search || undefined,
      health_min: filters.healthMin,
      health_max: filters.healthMax,
      make: filters.make,
      status: filters.status,
    },
    schema: fleetHealthResponseSchema,
  })
}

/** How many items the dashboard's "Upcoming & overdue" card shows; "View all" opens the full Maintenance page. */
export const CALENDAR_WIDGET_LIMIT = 7

/** The latest-due items first, only the top CALENDAR_WIDGET_LIMIT: sorted and limited by the backend. */
export function useMaintenanceCalendarPages(windowDays: number, search?: string) {
  return useQuery({
    queryKey: dashboardKeys.maintenanceCalendarPages(windowDays, search),
    queryFn: () =>
      apiRequestPage("/dashboard/maintenance-calendar", {
        query: { window_days: windowDays, limit: CALENDAR_WIDGET_LIMIT, search: search || undefined },
        schema: maintenanceCalendarResponseSchema,
      }),
    select: (page): PagedList<MaintenanceCalendarItem> => ({ items: page.items.slice(0, CALENDAR_WIDGET_LIMIT), total: page.total }),
  })
}

/** Worst health first, one page at a time. */
export function useFleetHealthPages(filters: FleetHealthFilters = {}, options?: { enabled?: boolean }) {
  return useInfiniteQuery({
    queryKey: dashboardKeys.fleetHealthPages(filters),
    queryFn: ({ pageParam }) => getFleetHealthPage(pageParam, filters),
    initialPageParam: 0,
    getNextPageParam: (last, all) => nextOffset(all, last, DASHBOARD_PAGE_SIZE),
    select: (data): PagedList<VehicleHealthScore> => toPagedList(data),
    enabled: options?.enabled ?? true,
  })
}

/** The distinct vehicle makes, for the Make filter. */
export function useFleetMakes() {
  return useQuery({
    queryKey: dashboardKeys.fleetMakes(),
    queryFn: () => apiRequest("/dashboard/fleet-makes", { schema: z.array(z.string()) }),
    staleTime: 5 * 60_000,
  })
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

export function useFleetHealth(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: dashboardKeys.fleetHealth(),
    queryFn: getFleetHealth,
    enabled: options?.enabled ?? true,
  })
}
