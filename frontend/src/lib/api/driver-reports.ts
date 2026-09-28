import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { z } from "zod"
import { driverReportKeys } from "@/lib/query/keys"
import {
  driverReportSchema,
  type DriverReport,
  type DriverReportCreate,
  type DriverReportListParams,
} from "@/lib/schemas/driver-report"
import { apiRequest } from "./client"

// Append-only: no update function exists here because the backend has no
// update schema and PATCH/PUT return 405 (CLAUDE.md §2.1) — never render an
// edit action for a shift report.

export function listDriverReports(params: DriverReportListParams = {}): Promise<DriverReport[]> {
  return apiRequest("/driver-reports", { query: params, schema: z.array(driverReportSchema) })
}

export function getDriverReport(id: string): Promise<DriverReport> {
  return apiRequest(`/driver-reports/${id}`, { schema: driverReportSchema })
}

// A/D only.
export function createDriverReport(input: DriverReportCreate): Promise<DriverReport> {
  return apiRequest("/driver-reports", { method: "POST", body: input, schema: driverReportSchema })
}

export function useDriverReports(params: DriverReportListParams = {}) {
  return useQuery({ queryKey: driverReportKeys.list(params), queryFn: () => listDriverReports(params) })
}

export function useCreateDriverReport() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createDriverReport,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: driverReportKeys.all }),
  })
}
