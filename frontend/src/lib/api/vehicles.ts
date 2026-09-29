import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { z } from "zod"
import { dashboardKeys, driverKeys, vehicleKeys } from "@/lib/query/keys"
import {
  vehicleAssignmentSchema,
  type VehicleAssignment,
  type VehicleAssignRequest,
  type VehicleReleaseRequest,
} from "@/lib/schemas/assignment"
import { vehicleComplianceResponseSchema, type VehicleComplianceResponse } from "@/lib/schemas/compliance"
import { timelineResponseSchema, type TimelineResponse } from "@/lib/schemas/timeline"
import { vehicleSchema, type Vehicle, type VehicleCreate, type VehicleUpdate } from "@/lib/schemas/vehicle"
import { apiRequest } from "./client"

// --- Reads -------------------------------------------------------------

export function listVehicles(): Promise<Vehicle[]> {
  return apiRequest("/vehicles", { schema: z.array(vehicleSchema) })
}

export function getVehicle(id: string): Promise<Vehicle> {
  return apiRequest(`/vehicles/${id}`, { schema: vehicleSchema })
}

export function getVehicleTimeline(id: string): Promise<TimelineResponse> {
  return apiRequest(`/vehicles/${id}/timeline`, { schema: timelineResponseSchema })
}

export function getVehicleCompliance(id: string): Promise<VehicleComplianceResponse> {
  return apiRequest(`/vehicles/${id}/compliance`, { schema: vehicleComplianceResponseSchema })
}

export function getVehicleAssignments(id: string, targetDate?: string): Promise<VehicleAssignment[]> {
  return apiRequest(`/vehicles/${id}/assignments`, {
    query: { target_date: targetDate },
    schema: z.array(vehicleAssignmentSchema),
  })
}

// --- Writes (A/FM only) --------------------------------------------------

export function createVehicle(input: VehicleCreate): Promise<Vehicle> {
  return apiRequest("/vehicles", { method: "POST", body: input, schema: vehicleSchema })
}

export function updateVehicle(id: string, input: VehicleUpdate): Promise<Vehicle> {
  return apiRequest(`/vehicles/${id}`, { method: "PUT", body: input, schema: vehicleSchema })
}

export function deleteVehicle(id: string): Promise<void> {
  return apiRequest(`/vehicles/${id}`, { method: "DELETE" })
}

export function assignVehicle(id: string, input: VehicleAssignRequest): Promise<VehicleAssignment> {
  return apiRequest(`/vehicles/${id}/assign`, { method: "POST", body: input, schema: vehicleAssignmentSchema })
}

export function releaseVehicle(id: string, input: VehicleReleaseRequest): Promise<VehicleAssignment> {
  return apiRequest(`/vehicles/${id}/release`, { method: "POST", body: input, schema: vehicleAssignmentSchema })
}

// --- Hooks -------------------------------------------------------------

export function useVehicles() {
  return useQuery({ queryKey: vehicleKeys.list(), queryFn: listVehicles })
}

export function useVehicle(id: string) {
  return useQuery({ queryKey: vehicleKeys.detail(id), queryFn: () => getVehicle(id), enabled: Boolean(id) })
}

export function useVehicleTimeline(id: string) {
  return useQuery({ queryKey: vehicleKeys.timeline(id), queryFn: () => getVehicleTimeline(id), enabled: Boolean(id) })
}

export function useVehicleCompliance(id: string) {
  return useQuery({
    queryKey: vehicleKeys.compliance(id),
    queryFn: () => getVehicleCompliance(id),
    enabled: Boolean(id),
  })
}

export function useVehicleAssignments(id: string, targetDate?: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: vehicleKeys.assignments(id, targetDate),
    queryFn: () => getVehicleAssignments(id, targetDate),
    enabled: Boolean(id) && (options?.enabled ?? true),
  })
}

export function useCreateVehicle() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createVehicle,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: vehicleKeys.list() }),
  })
}

export function useUpdateVehicle(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: VehicleUpdate) => updateVehicle(id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: vehicleKeys.list() })
      queryClient.invalidateQueries({ queryKey: vehicleKeys.detail(id) })
    },
  })
}

export function useDeleteVehicle() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteVehicle,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: vehicleKeys.list() }),
  })
}

// Assignment mutations invalidate vehicle AND driver histories plus the
// dashboard (CLAUDE.md §5.1) — never optimistic (custody, not idempotent).
export function useAssignVehicle(vehicleId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: VehicleAssignRequest) => assignVehicle(vehicleId, input),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: vehicleKeys.assignments(vehicleId) })
      queryClient.invalidateQueries({ queryKey: vehicleKeys.detail(vehicleId) })
      queryClient.invalidateQueries({ queryKey: driverKeys.assignments(data.driver_id) })
      queryClient.invalidateQueries({ queryKey: dashboardKeys.all })
    },
  })
}

export function useReleaseVehicle(vehicleId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: VehicleReleaseRequest) => releaseVehicle(vehicleId, input),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: vehicleKeys.assignments(vehicleId) })
      queryClient.invalidateQueries({ queryKey: vehicleKeys.detail(vehicleId) })
      queryClient.invalidateQueries({ queryKey: driverKeys.assignments(data.driver_id) })
      queryClient.invalidateQueries({ queryKey: dashboardKeys.all })
    },
  })
}
