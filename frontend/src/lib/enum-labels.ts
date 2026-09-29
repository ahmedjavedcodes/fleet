import type { StatusPillTone } from "@/components/primitives/status-pill"
import type {
  DocumentStatus,
  DocumentType,
  IncidentResolutionStatus,
  IncidentSeverity,
  IncidentType,
  ServiceType,
  VehicleCondition,
} from "@/lib/schemas/enums"

// Display labels for backend enums that need one — shared across dashboard,
// maintenance, accountability and vehicle-detail pages so the wording never
// drifts between them.
export const SERVICE_TYPE_LABELS: Record<ServiceType, string> = {
  oil_change: "Oil change",
  brake_service: "Brake service",
  tire_rotation: "Tire rotation",
  engine_repair: "Engine repair",
  transmission: "Transmission",
  electrical: "Electrical",
  body_work: "Body work",
  general_inspection: "General inspection",
  other: "Other",
}

export const INCIDENT_SEVERITY_LABELS: Record<IncidentSeverity, string> = {
  minor: "Minor",
  moderate: "Moderate",
  severe: "Severe",
  critical: "Critical",
}

// The sev-* StatusPill tones already mirror IncidentSeverity exactly
// (CLAUDE.md §1.2's severity scale).
export const INCIDENT_SEVERITY_TONE: Record<IncidentSeverity, StatusPillTone> = {
  minor: "sev-minor",
  moderate: "sev-moderate",
  severe: "sev-severe",
  critical: "sev-critical",
}

export const INCIDENT_TYPE_LABELS: Record<IncidentType, string> = {
  damage: "Damage",
  violation: "Violation",
  near_miss: "Near miss",
}

export const INCIDENT_RESOLUTION_LABELS: Record<IncidentResolutionStatus, string> = {
  open: "Open",
  investigating: "Investigating",
  resolved: "Resolved",
  closed: "Closed",
}

export const VEHICLE_CONDITION_LABELS: Record<VehicleCondition, string> = {
  good: "Good",
  fair: "Fair",
  poor: "Poor",
}

export const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  manual: "Manual",
  policy: "Policy",
  supplier_invoice: "Supplier invoice",
  incident_report: "Incident report",
  legal: "Legal",
}

export const DOCUMENT_STATUS_TONE: Record<DocumentStatus, StatusPillTone> = {
  processing: "info",
  ready: "success",
  failed: "destructive",
}
