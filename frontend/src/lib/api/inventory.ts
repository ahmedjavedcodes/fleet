import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { z } from "zod"
import { inventoryKeys } from "@/lib/query/keys"
import {
  lowStockResponseSchema,
  partsInventorySchema,
  type LowStockResponse,
  type PartsInventory,
  type PartsInventoryCreate,
  type PartsInventoryListParams,
  type PartsInventoryUpdate,
} from "@/lib/schemas/inventory"
import { apiRequest } from "./client"

export function listParts(params: PartsInventoryListParams = {}): Promise<PartsInventory[]> {
  return apiRequest("/inventory", { query: params, schema: z.array(partsInventorySchema) })
}

// A/FM/M.
export function listLowStockParts(): Promise<LowStockResponse[]> {
  return apiRequest("/inventory/low-stock", { schema: z.array(lowStockResponseSchema) })
}

// A/FM only.
export function createPart(input: PartsInventoryCreate): Promise<PartsInventory> {
  return apiRequest("/inventory", { method: "POST", body: input, schema: partsInventorySchema })
}

export function updatePart(id: string, input: PartsInventoryUpdate): Promise<PartsInventory> {
  return apiRequest(`/inventory/${id}`, { method: "PUT", body: input, schema: partsInventorySchema })
}

export function useParts(params: PartsInventoryListParams = {}) {
  return useQuery({ queryKey: inventoryKeys.list(params), queryFn: () => listParts(params) })
}

export function useLowStockParts() {
  return useQuery({ queryKey: inventoryKeys.lowStock(), queryFn: listLowStockParts })
}

export function useCreatePart() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createPart,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: inventoryKeys.all }),
  })
}

export function useUpdatePart(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: PartsInventoryUpdate) => updatePart(id, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: inventoryKeys.all }),
  })
}
