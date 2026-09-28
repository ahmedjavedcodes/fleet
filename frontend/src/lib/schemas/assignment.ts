import { z } from "zod"
import { dateTimeStringSchema, uuidSchema } from "./common"
import { vehicleConditionSchema } from "./enums"

// Mirrors backend/app/schemas/assignment.py. Assignments are custody records
// (assigned_at/released_at), not future schedules — never build a scheduler
// against this data (CLAUDE.md §2.1).

export const vehicleAssignRequestSchema = z
  .object({
    driver_id: uuidSchema,
    assigned_at: dateTimeStringSchema,
    start_odometer: z.number().int().positive(),
    take_condition: vehicleConditionSchema,
    take_notes: z.string().optional(),
  })
  .strict()
export type VehicleAssignRequest = z.infer<typeof vehicleAssignRequestSchema>

export const vehicleReleaseRequestSchema = z
  .object({
    released_at: dateTimeStringSchema,
    end_odometer: z.number().int().positive(),
    leave_condition: vehicleConditionSchema,
    leave_notes: z.string().optional(),
  })
  .strict()
export type VehicleReleaseRequest = z.infer<typeof vehicleReleaseRequestSchema>

export const vehicleAssignmentSchema = z.object({
  id: uuidSchema,
  vehicle_id: uuidSchema,
  driver_id: uuidSchema,
  assigned_at: dateTimeStringSchema,
  released_at: dateTimeStringSchema.nullable(),
  start_odometer: z.number().int(),
  end_odometer: z.number().int().nullable(),
  take_condition: vehicleConditionSchema,
  leave_condition: vehicleConditionSchema.nullable(),
  take_notes: z.string().nullable(),
  leave_notes: z.string().nullable(),
  created_at: dateTimeStringSchema,
  // null while the assignment is active (released_at is null).
  duration_hours: z.number().nullable(),
})
export type VehicleAssignment = z.infer<typeof vehicleAssignmentSchema>

export const driverAssignmentHistoryResponseSchema = z.object({
  driver_id: uuidSchema,
  current_assignment: vehicleAssignmentSchema.nullable(),
  total_vehicles_driven: z.number().int(),
  history: z.array(vehicleAssignmentSchema),
})
export type DriverAssignmentHistoryResponse = z.infer<typeof driverAssignmentHistoryResponseSchema>
