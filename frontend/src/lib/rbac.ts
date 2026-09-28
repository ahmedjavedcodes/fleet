import type { DocumentType, UserRole } from "@/lib/schemas/enums"

// The route/action → roles matrix (CLAUDE.md §5.3, plans/02 §9), taken from
// the backend's require_role(...) tuples in backend/app/api/*.py and
// verified against them directly. The backend is authoritative: if this
// drifts from the backend, the backend is right and this file gets fixed
// (CLAUDE.md §5.3, §8) — re-verify whenever a route's role gate changes.
//
// This is UX only. Hiding a button or nav item for a role is courtesy; the
// backend's 403 is the enforcement, and every call must still handle one
// gracefully regardless of what this file says (CLAUDE.md non-negotiable #3).

const A: UserRole = "admin"
const FM: UserRole = "fleet_manager"
const M: UserRole = "mechanic"
const D: UserRole = "driver"

export type RbacAction =
  | "vehicle:read"
  | "vehicle:timeline"
  | "vehicle:compliance"
  | "vehicle:write"
  | "vehicle:assign"
  | "vehicle:release"
  | "vehicle:assignments:read"
  | "driver:read"
  | "driver:write"
  | "driver:timeline"
  | "driver:assignments"
  | "supplier:read"
  | "supplier:write"
  | "fuel:read"
  | "fuel:write"
  | "fuel:receipt:upload"
  | "fuel:summary"
  | "trip:read"
  | "trip:write"
  | "maintenance:read"
  | "maintenance:write"
  | "maintenance:mechanic-report"
  | "maintenance:upcoming"
  | "maintenance:overdue"
  | "compliance:read"
  | "compliance:write"
  | "inventory:read"
  | "inventory:write"
  | "po:read"
  | "po:write"
  | "po:receive"
  | "driver-report:read"
  | "driver-report:write"
  | "incident:read"
  | "incident:create"
  | "incident:resolve"
  | "dashboard:read"
  | "document:read"
  | "document:search"
  | "document:upload"
  | "document:delete"

const MATRIX: Record<RbacAction, readonly UserRole[]> = {
  "vehicle:read": [A, FM, M, D],
  "vehicle:timeline": [A, FM, M, D],
  "vehicle:compliance": [A, FM, M, D],
  "vehicle:write": [A, FM],
  "vehicle:assign": [A, FM],
  "vehicle:release": [A, FM],
  // Stricter than vehicle:read — the assignments endpoints are gated
  // separately on the backend and exclude mechanic.
  "vehicle:assignments:read": [A, FM, D],

  "driver:read": [A, FM, M, D],
  "driver:write": [A, FM],
  // Also excludes mechanic (driver timeline/assignments are A/FM/D only).
  "driver:timeline": [A, FM, D],
  "driver:assignments": [A, FM, D],

  "supplier:read": [A, FM, M, D],
  "supplier:write": [A, FM],

  "fuel:read": [A, FM, D],
  "fuel:write": [A, D],
  "fuel:receipt:upload": [A, D],
  "fuel:summary": [A, FM],

  "trip:read": [A, FM, D],
  "trip:write": [A, D],

  "maintenance:read": [A, FM, M],
  "maintenance:write": [A, M],
  "maintenance:mechanic-report": [A, M],
  "maintenance:upcoming": [A, FM],
  "maintenance:overdue": [A, FM],

  "compliance:read": [A, FM, M],
  "compliance:write": [A, FM],

  "inventory:read": [A, FM, M],
  "inventory:write": [A, FM],

  "po:read": [A, FM, M],
  "po:write": [A, FM],
  "po:receive": [A, FM],

  "driver-report:read": [A, FM, D],
  "driver-report:write": [A, D],

  "incident:read": [A, FM, D],
  "incident:create": [A, FM, D],
  "incident:resolve": [A, FM],

  "dashboard:read": [A, FM],

  "document:read": [A, FM, M, D],
  "document:search": [A, FM, M, D],
  "document:upload": [A, FM],
  "document:delete": [A, FM],
}

export function can(role: UserRole, action: RbacAction): boolean {
  return MATRIX[action].includes(role)
}

// Sidebar nav groups/items (plans/00 §4, CLAUDE.md §3). Longest-prefix match
// so /foundation/vehicles doesn't fall through to a looser /foundation entry.
const ROUTE_ROLES: readonly { prefix: string; roles: readonly UserRole[] }[] = [
  { prefix: "/dashboard", roles: [A, FM, M, D] },
  { prefix: "/chat", roles: [A, FM, M, D] },
  { prefix: "/foundation/vehicles", roles: [A, FM, M, D] },
  { prefix: "/foundation/drivers", roles: [A, FM, M, D] },
  { prefix: "/foundation/suppliers", roles: [A, FM, M, D] },
  { prefix: "/foundation", roles: [A, FM, M, D] },
  { prefix: "/assignment", roles: [A, FM, D] },
  { prefix: "/fuel", roles: [A, FM, D] },
  { prefix: "/maintenance", roles: [A, FM, M] },
  { prefix: "/accountability", roles: [A, FM, D] },
  { prefix: "/documents", roles: [A, FM, M, D] },
  { prefix: "/insights", roles: [A, FM] },
  { prefix: "/notifications", roles: [A, FM, M, D] },
]

/** True if `role` may open `pathname` at all. Unlisted paths (not yet built,
 * or intentionally ungated) are allowed — this function only *restricts*
 * routes that appear in the matrix, it never expands access beyond it. */
export function routeAccess(role: UserRole, pathname: string): boolean {
  const match = ROUTE_ROLES.filter((r) => pathname === r.prefix || pathname.startsWith(`${r.prefix}/`)).sort(
    (a, b) => b.prefix.length - a.prefix.length
  )[0]
  return match ? match.roles.includes(role) : true
}

// Document visibility matrix (CLAUDE.md §2.1). A UX mirror for filters only
// — never relied on for security; the backend scopes the actual results.
const DOCUMENT_TYPES_BY_ROLE: Record<UserRole, readonly DocumentType[]> = {
  admin: ["manual", "policy", "supplier_invoice", "incident_report", "legal"],
  fleet_manager: ["manual", "policy", "supplier_invoice", "incident_report"],
  mechanic: ["manual", "policy"],
  driver: ["manual", "policy"],
}

export function visibleDocumentTypes(role: UserRole): readonly DocumentType[] {
  return DOCUMENT_TYPES_BY_ROLE[role]
}
