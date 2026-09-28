import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { z } from "zod"
import { complianceKeys, vehicleKeys } from "@/lib/query/keys"
import {
  complianceRuleSchema,
  fleetComplianceMatrixResponseSchema,
  vehicleComplianceResponseSchema,
  type ComplianceRule,
  type ComplianceRuleCreate,
  type ComplianceRuleListParams,
  type ComplianceRuleUpdate,
  type FleetComplianceMatrixResponse,
  type VehicleComplianceResponse,
} from "@/lib/schemas/compliance"
import { apiRequest } from "./client"

export function listComplianceRules(params: ComplianceRuleListParams = {}): Promise<ComplianceRule[]> {
  return apiRequest("/compliance/rules", { query: params, schema: z.array(complianceRuleSchema) })
}

export function getFleetComplianceMatrix(): Promise<FleetComplianceMatrixResponse> {
  return apiRequest("/compliance/status", { schema: fleetComplianceMatrixResponseSchema })
}

export function getVehicleComplianceStatus(vehicleId: string): Promise<VehicleComplianceResponse> {
  return apiRequest(`/compliance/status/${vehicleId}`, { schema: vehicleComplianceResponseSchema })
}

// A/FM only.
export function createComplianceRule(input: ComplianceRuleCreate): Promise<ComplianceRule> {
  return apiRequest("/compliance/rules", { method: "POST", body: input, schema: complianceRuleSchema })
}

export function updateComplianceRule(id: string, input: ComplianceRuleUpdate): Promise<ComplianceRule> {
  return apiRequest(`/compliance/rules/${id}`, { method: "PUT", body: input, schema: complianceRuleSchema })
}

export function useComplianceRules(params: ComplianceRuleListParams = {}) {
  return useQuery({ queryKey: complianceKeys.rules(params), queryFn: () => listComplianceRules(params) })
}

export function useFleetComplianceMatrix() {
  return useQuery({ queryKey: complianceKeys.statusMatrix(), queryFn: getFleetComplianceMatrix })
}

export function useVehicleComplianceStatus(vehicleId: string) {
  return useQuery({
    queryKey: complianceKeys.statusFor(vehicleId),
    queryFn: () => getVehicleComplianceStatus(vehicleId),
    enabled: Boolean(vehicleId),
  })
}

// A rule change affects every vehicle's computed compliance status —
// invalidate the whole compliance domain plus per-vehicle compliance caches
// (used on the vehicle detail page, plans/05 §2.4).
export function useCreateComplianceRule() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createComplianceRule,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: complianceKeys.all })
      queryClient.invalidateQueries({ queryKey: vehicleKeys.all })
    },
  })
}

export function useUpdateComplianceRule(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: ComplianceRuleUpdate) => updateComplianceRule(id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: complianceKeys.all })
      queryClient.invalidateQueries({ queryKey: vehicleKeys.all })
    },
  })
}
