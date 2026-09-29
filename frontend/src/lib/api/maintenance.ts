import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { z } from "zod"
import { dashboardKeys, inventoryKeys, maintenanceKeys } from "@/lib/query/keys"
import {
  maintenanceLogSchema,
  mechanicReportSchema,
  overdueMaintenanceItemSchema,
  upcomingMaintenanceItemSchema,
  type MaintenanceLog,
  type MaintenanceLogCreate,
  type MaintenanceLogListParams,
  type MaintenanceLogUpdate,
  type MechanicReport,
  type MechanicReportCreate,
  type OverdueMaintenanceItem,
  type UpcomingMaintenanceItem,
} from "@/lib/schemas/maintenance"
import { apiRequest } from "./client"

// --- Reads -------------------------------------------------------------

export function listMaintenanceLogs(params: MaintenanceLogListParams = {}): Promise<MaintenanceLog[]> {
  return apiRequest("/maintenance", { query: params, schema: z.array(maintenanceLogSchema) })
}

export function getMaintenanceLog(id: string): Promise<MaintenanceLog> {
  return apiRequest(`/maintenance/${id}`, { schema: maintenanceLogSchema })
}

// A/FM only.
export function listUpcomingMaintenance(windowKm?: number): Promise<UpcomingMaintenanceItem[]> {
  return apiRequest("/maintenance/upcoming", { query: { window_km: windowKm }, schema: z.array(upcomingMaintenanceItemSchema) })
}

// A/FM only.
export function listOverdueMaintenance(): Promise<OverdueMaintenanceItem[]> {
  return apiRequest("/maintenance/overdue", { schema: z.array(overdueMaintenanceItemSchema) })
}

// --- Writes (A/M only) ----------------------------------------------------

export function createMaintenanceLog(input: MaintenanceLogCreate): Promise<MaintenanceLog> {
  return apiRequest("/maintenance", { method: "POST", body: input, schema: maintenanceLogSchema })
}

export function updateMaintenanceLog(id: string, input: MaintenanceLogUpdate): Promise<MaintenanceLog> {
  return apiRequest(`/maintenance/${id}`, { method: "PUT", body: input, schema: maintenanceLogSchema })
}

export function createMechanicReport(logId: string, input: MechanicReportCreate): Promise<MechanicReport> {
  return apiRequest(`/maintenance/${logId}/mechanic-report`, { method: "POST", body: input, schema: mechanicReportSchema })
}

// --- Hooks -------------------------------------------------------------

export function useMaintenanceLogs(params: MaintenanceLogListParams = {}, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: maintenanceKeys.list(params),
    queryFn: () => listMaintenanceLogs(params),
    enabled: options?.enabled ?? true,
  })
}

export function useMaintenanceLog(id: string) {
  return useQuery({ queryKey: maintenanceKeys.detail(id), queryFn: () => getMaintenanceLog(id), enabled: Boolean(id) })
}

export function useUpcomingMaintenance(windowKm?: number) {
  return useQuery({ queryKey: maintenanceKeys.upcoming(windowKm), queryFn: () => listUpcomingMaintenance(windowKm) })
}

export function useOverdueMaintenance() {
  return useQuery({ queryKey: maintenanceKeys.overdue(), queryFn: listOverdueMaintenance })
}

export function useCreateMaintenanceLog() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createMaintenanceLog,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: maintenanceKeys.all })
      queryClient.invalidateQueries({ queryKey: dashboardKeys.summary() })
      queryClient.invalidateQueries({ queryKey: dashboardKeys.maintenanceCalendar() })
    },
  })
}

export function useUpdateMaintenanceLog(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: MaintenanceLogUpdate) => updateMaintenanceLog(id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: maintenanceKeys.all })
      queryClient.invalidateQueries({ queryKey: dashboardKeys.maintenanceCalendar() })
    },
  })
}

// A mechanic report can decrement parts stock (low_stock_alerts on the
// response) — invalidate inventory too.
export function useCreateMechanicReport(logId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: MechanicReportCreate) => createMechanicReport(logId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: maintenanceKeys.detail(logId) })
      queryClient.invalidateQueries({ queryKey: inventoryKeys.all })
    },
  })
}
