import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { z } from "zod"
import { dashboardKeys, incidentKeys } from "@/lib/query/keys"
import {
  incidentLogSchema,
  type IncidentLog,
  type IncidentLogCreate,
  type IncidentLogListParams,
  type IncidentLogResolutionUpdate,
} from "@/lib/schemas/incident"
import { apiRequest } from "./client"

// Incidents are immutable — updateIncidentResolution is the ONLY write path
// after creation (only resolution_status/resolution_notes change; the
// backend's IncidentLogResolutionUpdate schema enforces this at the API
// boundary, extra="forbid", not just a UI convention — CLAUDE.md §2.1).

export function listIncidents(params: IncidentLogListParams = {}): Promise<IncidentLog[]> {
  return apiRequest("/incidents", { query: params, schema: z.array(incidentLogSchema) })
}

export function getIncident(id: string): Promise<IncidentLog> {
  return apiRequest(`/incidents/${id}`, { schema: incidentLogSchema })
}

// A/FM/D.
export function createIncident(input: IncidentLogCreate): Promise<IncidentLog> {
  return apiRequest("/incidents", { method: "POST", body: input, schema: incidentLogSchema })
}

// A/FM only.
export function updateIncidentResolution(id: string, input: IncidentLogResolutionUpdate): Promise<IncidentLog> {
  return apiRequest(`/incidents/${id}`, { method: "PUT", body: input, schema: incidentLogSchema })
}

export function useIncidents(params: IncidentLogListParams = {}) {
  return useQuery({ queryKey: incidentKeys.list(params), queryFn: () => listIncidents(params) })
}

export function useIncident(id: string) {
  return useQuery({ queryKey: incidentKeys.detail(id), queryFn: () => getIncident(id), enabled: Boolean(id) })
}

export function useCreateIncident() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createIncident,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: incidentKeys.all })
      queryClient.invalidateQueries({ queryKey: dashboardKeys.summary() })
    },
  })
}

export function useUpdateIncidentResolution(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: IncidentLogResolutionUpdate) => updateIncidentResolution(id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: incidentKeys.all })
      queryClient.invalidateQueries({ queryKey: dashboardKeys.summary() })
    },
  })
}
