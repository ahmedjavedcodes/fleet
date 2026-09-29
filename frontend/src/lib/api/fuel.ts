import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query"
import { z } from "zod"
import { dashboardKeys, fuelKeys } from "@/lib/query/keys"
import {
  fuelLogSchema,
  fuelReceiptSchema,
  fuelSummaryResponseSchema,
  type FuelLog,
  type FuelLogCreate,
  type FuelLogListParams,
  type FuelLogUpdate,
  type FuelReceipt,
  type FuelSummaryResponse,
} from "@/lib/schemas/fuel"
import { apiRequest } from "./client"

// --- Reads -------------------------------------------------------------

export function listFuelLogs(params: FuelLogListParams = {}): Promise<FuelLog[]> {
  return apiRequest("/fuel", { query: params, schema: z.array(fuelLogSchema) })
}

export function getFuelLog(id: string): Promise<FuelLog> {
  return apiRequest(`/fuel/${id}`, { schema: fuelLogSchema })
}

// A/FM only.
export function getFuelSummary(month?: string): Promise<FuelSummaryResponse> {
  return apiRequest("/fuel/summary", { query: { month }, schema: fuelSummaryResponseSchema })
}

// --- Writes (A/D only) ---------------------------------------------------

export function createFuelLog(input: FuelLogCreate): Promise<FuelLog> {
  return apiRequest("/fuel", { method: "POST", body: input, schema: fuelLogSchema })
}

export function updateFuelLog(id: string, input: FuelLogUpdate): Promise<FuelLog> {
  return apiRequest(`/fuel/${id}`, { method: "PUT", body: input, schema: fuelLogSchema })
}

// Multipart: pdf, jpeg, png or webp. A second receipt on the same log
// returns 409 — check `log.receipt` before offering this action.
export function attachFuelReceipt(id: string, file: File): Promise<FuelReceipt> {
  const formData = new FormData()
  formData.append("file", file)
  return apiRequest(`/fuel/${id}/receipt`, { method: "POST", body: formData, schema: fuelReceiptSchema })
}

// --- Hooks -------------------------------------------------------------

export function useFuelLogs(params: FuelLogListParams = {}, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: fuelKeys.list(params),
    queryFn: () => listFuelLogs(params),
    enabled: options?.enabled ?? true,
  })
}

export function useFuelLog(id: string) {
  return useQuery({ queryKey: fuelKeys.detail(id), queryFn: () => getFuelLog(id), enabled: Boolean(id) })
}

export function useFuelSummary(month?: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: fuelKeys.summary(month),
    queryFn: () => getFuelSummary(month),
    enabled: options?.enabled ?? true,
  })
}

// A fuel log invalidates fuel lists, fuel summary and dashboard trends
// (CLAUDE.md §5.1) — every cached filter/month variant of each, via the
// short-prefix keys (plans/02 §7).
function invalidateFuel(queryClient: QueryClient) {
  queryClient.invalidateQueries({ queryKey: fuelKeys.all })
  queryClient.invalidateQueries({ queryKey: dashboardKeys.fuelTrends() })
  queryClient.invalidateQueries({ queryKey: dashboardKeys.summary() })
}

export function useCreateFuelLog() {
  const queryClient = useQueryClient()
  return useMutation({ mutationFn: createFuelLog, onSuccess: () => invalidateFuel(queryClient) })
}

export function useUpdateFuelLog(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: FuelLogUpdate) => updateFuelLog(id, input),
    onSuccess: () => invalidateFuel(queryClient),
  })
}

export function useAttachFuelReceipt(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => attachFuelReceipt(id, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: fuelKeys.detail(id) })
      queryClient.invalidateQueries({ queryKey: fuelKeys.list() })
    },
  })
}
