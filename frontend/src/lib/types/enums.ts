// Mirrors backend/app/models/enums.py. Keep values in sync — the backend
// serializes these as plain strings, so a mismatch here fails silently
// (falls through `default` branches) rather than raising a type error.

export type UserRole = "admin" | "fleet_manager" | "driver" | "mechanic";

export type SubscriptionTier = "trial" | "starter" | "pro" | "enterprise";

export type DriverStatus = "active" | "suspended" | "inactive";

export type VehicleFuelType = "diesel" | "petrol" | "hybrid" | "electric";

export type VehicleStatus = "active" | "maintenance" | "retired";

export type FuelReceiptUploadStatus = "pending" | "parsed" | "failed";

export type PurchaseOrderStatus = "pending" | "shipped" | "received" | "cancelled";

export type ServiceType =
  | "oil_change"
  | "brake_service"
  | "tire_rotation"
  | "engine_repair"
  | "transmission"
  | "electrical"
  | "body_work"
  | "general_inspection"
  | "other";

export type VehicleCondition = "good" | "fair" | "poor";

export type IncidentType = "damage" | "violation" | "near_miss";

export type IncidentSeverity = "minor" | "moderate" | "severe" | "critical";

export type IncidentResolutionStatus = "open" | "investigating" | "resolved" | "closed";
