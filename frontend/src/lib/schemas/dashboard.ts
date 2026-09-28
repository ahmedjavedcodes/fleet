import { z } from "zod"
import { dateStringSchema, decimalStringSchema, uuidSchema } from "./common"
import { maintenanceCalendarStatusSchema, serviceTypeSchema } from "./enums"

// Mirrors backend/app/schemas/dashboard.py. Every endpoint here is
// Admin/Fleet-Manager only — never call these for M/D (CLAUDE.md §2.2).

export const dashboardSummaryResponseSchema = z.object({
  total_vehicles: z.number().int(),
  active_drivers: z.number().int(),
  month_fuel_cost: decimalStringSchema,
  overdue_maintenance_count: z.number().int(),
  low_stock_parts_count: z.number().int(),
  // Counts open + investigating incidents.
  open_incidents_count: z.number().int(),
})
export type DashboardSummaryResponse = z.infer<typeof dashboardSummaryResponseSchema>

export const fuelTrendPointSchema = z.object({
  month: z.string(),
  total_cost: decimalStringSchema,
  avg_cost_per_km: decimalStringSchema.nullable(),
})
export type FuelTrendPoint = z.infer<typeof fuelTrendPointSchema>

export const fuelTrendsResponseSchema = z.array(fuelTrendPointSchema)
export type FuelTrendsResponse = z.infer<typeof fuelTrendsResponseSchema>

export const maintenanceCalendarItemSchema = z.object({
  vehicle_id: uuidSchema,
  plate_number: z.string(),
  service_type: serviceTypeSchema,
  // Nullable: an item overdue purely by km has no next_due_date. Per the
  // backend, an overdue item is never dropped from the calendar for any
  // reason — it stays, with due_date null and due_km/status conveying it.
  due_date: dateStringSchema.nullable(),
  due_km: z.number().int().nullable(),
  status: maintenanceCalendarStatusSchema,
})
export type MaintenanceCalendarItem = z.infer<typeof maintenanceCalendarItemSchema>

export const maintenanceCalendarResponseSchema = z.array(maintenanceCalendarItemSchema)
export type MaintenanceCalendarResponse = z.infer<typeof maintenanceCalendarResponseSchema>

// Each signal is 0-100 or null (excluded from the weighted score, not scored
// as 0). Render "n/a" for null, never 0 (CLAUDE.md §4.4).
export const vehicleHealthSignalsSchema = z.object({
  compliance: z.number().int().nullable(),
  incidents: z.number().int().nullable(),
  maintenance_currency: z.number().int().nullable(),
  fuel_efficiency: z.number().int().nullable(),
})
export type VehicleHealthSignals = z.infer<typeof vehicleHealthSignalsSchema>

export const vehicleHealthScoreSchema = z.object({
  vehicle_id: uuidSchema,
  plate_number: z.string(),
  health_score: z.number().int(),
  signals: vehicleHealthSignalsSchema,
})
export type VehicleHealthScore = z.infer<typeof vehicleHealthScoreSchema>

export const fleetHealthResponseSchema = z.array(vehicleHealthScoreSchema)
export type FleetHealthResponse = z.infer<typeof fleetHealthResponseSchema>
