import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { z } from "zod"
import { driverKeys, vehicleKeys } from "@/lib/query/keys"
import { driverAssignmentHistoryResponseSchema, type DriverAssignmentHistoryResponse } from "@/lib/schemas/assignment"
import { driverSchema, type Driver, type DriverCreate, type DriverUpdate } from "@/lib/schemas/driver"
import { timelineResponseSchema, type TimelineResponse } from "@/lib/schemas/timeline"
import { apiRequest } from "./client"

// --- Reads -------------------------------------------------------------

export function listDrivers(): Promise<Driver[]> {
  return apiRequest("/drivers", { schema: z.array(driverSchema) })
}

export function getDriver(id: string): Promise<Driver> {
  return apiRequest(`/drivers/${id}`, { schema: driverSchema })
}

// A/FM/D — a driver may only request their own id (otherwise 403).
export function getDriverTimeline(id: string): Promise<TimelineResponse> {
  return apiRequest(`/drivers/${id}/timeline`, { schema: timelineResponseSchema })
}

export function getDriverAssignments(id: string): Promise<DriverAssignmentHistoryResponse> {
  return apiRequest(`/drivers/${id}/assignments`, { schema: driverAssignmentHistoryResponseSchema })
}

// --- Writes (A/FM only) --------------------------------------------------

export function createDriver(input: DriverCreate): Promise<Driver> {
  return apiRequest("/drivers", { method: "POST", body: input, schema: driverSchema })
}

export function updateDriver(id: string, input: DriverUpdate): Promise<Driver> {
  return apiRequest(`/drivers/${id}`, { method: "PUT", body: input, schema: driverSchema })
}

export function deleteDriver(id: string): Promise<void> {
  return apiRequest(`/drivers/${id}`, { method: "DELETE" })
}

// --- Hooks -------------------------------------------------------------

export function useDrivers() {
  return useQuery({ queryKey: driverKeys.list(), queryFn: listDrivers })
}

export function useDriver(id: string) {
  return useQuery({ queryKey: driverKeys.detail(id), queryFn: () => getDriver(id), enabled: Boolean(id) })
}

export function useDriverTimeline(id: string) {
  return useQuery({ queryKey: driverKeys.timeline(id), queryFn: () => getDriverTimeline(id), enabled: Boolean(id) })
}

export function useDriverAssignments(id: string) {
  return useQuery({
    queryKey: driverKeys.assignments(id),
    queryFn: () => getDriverAssignments(id),
    enabled: Boolean(id),
  })
}

export function useCreateDriver() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createDriver,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: driverKeys.list() }),
  })
}

export function useUpdateDriver(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: DriverUpdate) => updateDriver(id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: driverKeys.list() })
      queryClient.invalidateQueries({ queryKey: driverKeys.detail(id) })
    },
  })
}

export function useDeleteDriver() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteDriver,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: driverKeys.list() })
      // A deleted driver can no longer be "currently assigned" — vehicle
      // detail pages showing that assignment need to refetch too.
      queryClient.invalidateQueries({ queryKey: vehicleKeys.all })
    },
  })
}
