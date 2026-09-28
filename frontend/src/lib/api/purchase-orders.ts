import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { z } from "zod"
import { inventoryKeys, purchaseOrderKeys } from "@/lib/query/keys"
import {
  purchaseOrderReceiveResponseSchema,
  purchaseOrderSchema,
  type PurchaseOrder,
  type PurchaseOrderCreate,
  type PurchaseOrderListParams,
  type PurchaseOrderReceiveResponse,
  type PurchaseOrderUpdate,
} from "@/lib/schemas/purchase-order"
import { apiRequest } from "./client"

export function listPurchaseOrders(params: PurchaseOrderListParams = {}): Promise<PurchaseOrder[]> {
  return apiRequest("/purchase-orders", { query: params, schema: z.array(purchaseOrderSchema) })
}

// A/FM only.
export function createPurchaseOrder(input: PurchaseOrderCreate): Promise<PurchaseOrder> {
  return apiRequest("/purchase-orders", { method: "POST", body: input, schema: purchaseOrderSchema })
}

// Only pre-receive fields — receiving happens exclusively through receivePurchaseOrder.
export function updatePurchaseOrder(id: string, input: PurchaseOrderUpdate): Promise<PurchaseOrder> {
  return apiRequest(`/purchase-orders/${id}`, { method: "PUT", body: input, schema: purchaseOrderSchema })
}

export function receivePurchaseOrder(id: string): Promise<PurchaseOrderReceiveResponse> {
  return apiRequest(`/purchase-orders/${id}/receive`, { method: "PATCH", schema: purchaseOrderReceiveResponseSchema })
}

export function usePurchaseOrders(params: PurchaseOrderListParams = {}) {
  return useQuery({ queryKey: purchaseOrderKeys.list(params), queryFn: () => listPurchaseOrders(params) })
}

export function useCreatePurchaseOrder() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createPurchaseOrder,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: purchaseOrderKeys.all }),
  })
}

export function useUpdatePurchaseOrder(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: PurchaseOrderUpdate) => updatePurchaseOrder(id, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: purchaseOrderKeys.all }),
  })
}

// Receiving updates stock levels — invalidate inventory too.
export function useReceivePurchaseOrder(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => receivePurchaseOrder(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: purchaseOrderKeys.all })
      queryClient.invalidateQueries({ queryKey: inventoryKeys.all })
    },
  })
}
