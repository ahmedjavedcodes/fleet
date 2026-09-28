import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { z } from "zod"
import { supplierKeys } from "@/lib/query/keys"
import { supplierSchema, type Supplier, type SupplierCreate, type SupplierUpdate } from "@/lib/schemas/supplier"
import { apiRequest } from "./client"

// No GET-by-id and no DELETE on the backend — list and update only.

export function listSuppliers(sort?: "reliability_score"): Promise<Supplier[]> {
  return apiRequest("/suppliers", { query: { sort }, schema: z.array(supplierSchema) })
}

export function createSupplier(input: SupplierCreate): Promise<Supplier> {
  return apiRequest("/suppliers", { method: "POST", body: input, schema: supplierSchema })
}

export function updateSupplier(id: string, input: SupplierUpdate): Promise<Supplier> {
  return apiRequest(`/suppliers/${id}`, { method: "PUT", body: input, schema: supplierSchema })
}

export function useSuppliers(sort?: "reliability_score") {
  return useQuery({ queryKey: supplierKeys.list(sort), queryFn: () => listSuppliers(sort) })
}

export function useCreateSupplier() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createSupplier,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: supplierKeys.all }),
  })
}

export function useUpdateSupplier(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: SupplierUpdate) => updateSupplier(id, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: supplierKeys.all }),
  })
}
