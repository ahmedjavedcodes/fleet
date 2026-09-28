import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { z } from "zod"
import { tripKeys } from "@/lib/query/keys"
import { tripLogSchema, type TripLog, type TripLogCreate, type TripLogListParams } from "@/lib/schemas/trip"
import { apiRequest } from "./client"

// Both ends of a trip are required (CLAUDE.md §2.1) — there is no
// in-progress trip state and no separate "complete trip" endpoint.

export function listTrips(params: TripLogListParams = {}): Promise<TripLog[]> {
  return apiRequest("/trips", { query: params, schema: z.array(tripLogSchema) })
}

export function getTrip(id: string): Promise<TripLog> {
  return apiRequest(`/trips/${id}`, { schema: tripLogSchema })
}

// A/D only.
export function createTrip(input: TripLogCreate): Promise<TripLog> {
  return apiRequest("/trips", { method: "POST", body: input, schema: tripLogSchema })
}

export function useTrips(params: TripLogListParams = {}) {
  return useQuery({ queryKey: tripKeys.list(params), queryFn: () => listTrips(params) })
}

export function useTrip(id: string) {
  return useQuery({ queryKey: tripKeys.detail(id), queryFn: () => getTrip(id), enabled: Boolean(id) })
}

export function useCreateTrip() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createTrip,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: tripKeys.all }),
  })
}
