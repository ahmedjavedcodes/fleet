import { z } from "zod"

// Mirrors backend/app/models/enums.py exactly. Re-verify against that file
// whenever the backend changes (CLAUDE.md §8) — do not add, remove or rename
// a value without checking it there first.

export const subscriptionTierSchema = z.enum(["trial", "starter", "pro", "enterprise"])
export type SubscriptionTier = z.infer<typeof subscriptionTierSchema>

export const userRoleSchema = z.enum(["admin", "fleet_manager", "driver", "mechanic"])
export type UserRole = z.infer<typeof userRoleSchema>

export const driverStatusSchema = z.enum(["active", "suspended", "inactive"])
export type DriverStatus = z.infer<typeof driverStatusSchema>

export const vehicleFuelTypeSchema = z.enum(["diesel", "petrol", "hybrid", "electric"])
export type VehicleFuelType = z.infer<typeof vehicleFuelTypeSchema>

export const vehicleStatusSchema = z.enum(["active", "maintenance", "retired"])
export type VehicleStatus = z.infer<typeof vehicleStatusSchema>

export const fuelReceiptUploadStatusSchema = z.enum(["pending", "parsed", "failed"])
export type FuelReceiptUploadStatus = z.infer<typeof fuelReceiptUploadStatusSchema>

export const purchaseOrderStatusSchema = z.enum(["pending", "shipped", "received", "cancelled"])
export type PurchaseOrderStatus = z.infer<typeof purchaseOrderStatusSchema>

// Shared identically between ComplianceRule and MaintenanceLog on the backend.
export const serviceTypeSchema = z.enum([
  "oil_change",
  "brake_service",
  "tire_rotation",
  "engine_repair",
  "transmission",
  "electrical",
  "body_work",
  "general_inspection",
  "other",
])
export type ServiceType = z.infer<typeof serviceTypeSchema>

export const vehicleConditionSchema = z.enum(["good", "fair", "poor"])
export type VehicleCondition = z.infer<typeof vehicleConditionSchema>

export const incidentTypeSchema = z.enum(["damage", "violation", "near_miss"])
export type IncidentType = z.infer<typeof incidentTypeSchema>

export const incidentSeveritySchema = z.enum(["minor", "moderate", "severe", "critical"])
export type IncidentSeverity = z.infer<typeof incidentSeveritySchema>

export const incidentResolutionStatusSchema = z.enum(["open", "investigating", "resolved", "closed"])
export type IncidentResolutionStatus = z.infer<typeof incidentResolutionStatusSchema>

export const documentTypeSchema = z.enum(["manual", "policy", "supplier_invoice", "incident_report", "legal"])
export type DocumentType = z.infer<typeof documentTypeSchema>

export const documentStatusSchema = z.enum(["processing", "ready", "failed"])
export type DocumentStatus = z.infer<typeof documentStatusSchema>

// Schema-level literal unions (not backend enum.Enum classes, but fixed sets
// declared inline in the Pydantic schemas — CLAUDE.md §7 treats these the
// same way: string-literal unions, never hand-duplicated elsewhere).
export const complianceStatusSchema = z.enum(["compliant", "due_soon", "overdue", "never_performed"])
export type ComplianceStatus = z.infer<typeof complianceStatusSchema>

export const maintenanceCalendarStatusSchema = z.enum(["upcoming", "overdue"])
export type MaintenanceCalendarStatus = z.infer<typeof maintenanceCalendarStatusSchema>

export const timelineRecordTypeSchema = z.enum(["trip", "report", "incident"])
export type TimelineRecordType = z.infer<typeof timelineRecordTypeSchema>

// Added with backend migration expand_fleet_operational_fields.
export const vehicleOwnershipTypeSchema = z.enum(["leasing", "rent", "owner"])
export type VehicleOwnershipType = z.infer<typeof vehicleOwnershipTypeSchema>

export const supplierCategorySchema = z.enum(["workshop", "tire_supplier", "parts_supplier", "fuel_station", "other"])
export type SupplierCategory = z.infer<typeof supplierCategorySchema>

export const serviceScaleSchema = z.enum(["minor", "major"])
export type ServiceScale = z.infer<typeof serviceScaleSchema>
