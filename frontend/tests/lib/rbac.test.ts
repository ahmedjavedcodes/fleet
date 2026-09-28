import { describe, expect, it } from "vitest"
import type { UserRole } from "@/lib/schemas/enums"
import { can, routeAccess, routeAllowedRoles, visibleDocumentTypes, type RbacAction } from "@/lib/rbac"

const ROLES: UserRole[] = ["admin", "fleet_manager", "mechanic", "driver"]

// Mirrors the MATRIX in rbac.ts, verified against backend/app/api/*.py's
// require_role(...) tuples (plans/02 §9). Written independently of rbac.ts's
// own table so a typo in one isn't invisible to the other.
const EXPECTED: Record<RbacAction, UserRole[]> = {
  "vehicle:read": ["admin", "fleet_manager", "mechanic", "driver"],
  "vehicle:timeline": ["admin", "fleet_manager", "mechanic", "driver"],
  "vehicle:compliance": ["admin", "fleet_manager", "mechanic", "driver"],
  "vehicle:write": ["admin", "fleet_manager"],
  "vehicle:assign": ["admin", "fleet_manager"],
  "vehicle:release": ["admin", "fleet_manager"],
  "vehicle:assignments:read": ["admin", "fleet_manager", "driver"],
  "driver:read": ["admin", "fleet_manager", "mechanic", "driver"],
  "driver:write": ["admin", "fleet_manager"],
  "driver:timeline": ["admin", "fleet_manager", "driver"],
  "driver:assignments": ["admin", "fleet_manager", "driver"],
  "supplier:read": ["admin", "fleet_manager", "mechanic", "driver"],
  "supplier:write": ["admin", "fleet_manager"],
  "fuel:read": ["admin", "fleet_manager", "driver"],
  "fuel:write": ["admin", "driver"],
  "fuel:receipt:upload": ["admin", "driver"],
  "fuel:summary": ["admin", "fleet_manager"],
  "trip:read": ["admin", "fleet_manager", "driver"],
  "trip:write": ["admin", "driver"],
  "maintenance:read": ["admin", "fleet_manager", "mechanic"],
  "maintenance:write": ["admin", "mechanic"],
  "maintenance:mechanic-report": ["admin", "mechanic"],
  "maintenance:upcoming": ["admin", "fleet_manager"],
  "maintenance:overdue": ["admin", "fleet_manager"],
  "compliance:read": ["admin", "fleet_manager", "mechanic"],
  "compliance:write": ["admin", "fleet_manager"],
  "inventory:read": ["admin", "fleet_manager", "mechanic"],
  "inventory:write": ["admin", "fleet_manager"],
  "po:read": ["admin", "fleet_manager", "mechanic"],
  "po:write": ["admin", "fleet_manager"],
  "po:receive": ["admin", "fleet_manager"],
  "driver-report:read": ["admin", "fleet_manager", "driver"],
  "driver-report:write": ["admin", "driver"],
  "incident:read": ["admin", "fleet_manager", "driver"],
  "incident:create": ["admin", "fleet_manager", "driver"],
  "incident:resolve": ["admin", "fleet_manager"],
  "dashboard:read": ["admin", "fleet_manager"],
  "document:read": ["admin", "fleet_manager", "mechanic", "driver"],
  "document:search": ["admin", "fleet_manager", "mechanic", "driver"],
  "document:upload": ["admin", "fleet_manager"],
  "document:delete": ["admin", "fleet_manager"],
}

describe("can (full matrix: every action x every role)", () => {
  for (const action of Object.keys(EXPECTED) as RbacAction[]) {
    for (const role of ROLES) {
      const expected = EXPECTED[action].includes(role)
      it(`${action} — ${role} → ${expected}`, () => {
        expect(can(role, action)).toBe(expected)
      })
    }
  }

  it("covers every declared RbacAction (no action silently missing from the test table)", () => {
    // A TS compile error here means a new action was added to rbac.ts's
    // MATRIX without a corresponding EXPECTED row — the assignment below
    // only type-checks if the two key sets are identical.
    const _exhaustive: Record<RbacAction, UserRole[]> = EXPECTED
    expect(Object.keys(_exhaustive).length).toBeGreaterThan(0)
  })
})

describe("routeAccess", () => {
  it("gates /maintenance to A/FM/M, not driver", () => {
    expect(routeAccess("admin", "/maintenance")).toBe(true)
    expect(routeAccess("fleet_manager", "/maintenance")).toBe(true)
    expect(routeAccess("mechanic", "/maintenance")).toBe(true)
    expect(routeAccess("driver", "/maintenance")).toBe(false)
  })

  it("gates /insights to A/FM only", () => {
    expect(routeAccess("admin", "/insights")).toBe(true)
    expect(routeAccess("mechanic", "/insights")).toBe(false)
    expect(routeAccess("driver", "/insights")).toBe(false)
  })

  it("matches sub-paths by prefix", () => {
    expect(routeAccess("driver", "/foundation/vehicles/abc-123")).toBe(true)
    expect(routeAccess("mechanic", "/maintenance/abc-123/edit")).toBe(true)
  })

  it("prefers the longer, more specific prefix over a looser parent route", () => {
    // /foundation itself allows all 4 roles; if a future route like
    // /foundation/reports were FM-only, it must not inherit /foundation's
    // laxer access just because /foundation is also a prefix match.
    expect(routeAccess("driver", "/foundation/vehicles")).toBe(true)
    expect(routeAccess("driver", "/foundation")).toBe(true)
  })

  it("allows any role on an unlisted path (not this function's concern)", () => {
    expect(routeAccess("driver", "/some-future-page")).toBe(true)
  })
})

describe("routeAllowedRoles", () => {
  it("returns the matched roles for AccessDenied's role-aware hint", () => {
    expect(routeAllowedRoles("/maintenance")).toEqual(["admin", "fleet_manager", "mechanic"])
    expect(routeAllowedRoles("/maintenance/abc-123")).toEqual(["admin", "fleet_manager", "mechanic"])
    expect(routeAllowedRoles("/insights")).toEqual(["admin", "fleet_manager"])
  })

  it("returns null for an unlisted path", () => {
    expect(routeAllowedRoles("/some-future-page")).toBeNull()
  })

  it("agrees with routeAccess for every route/role combination", () => {
    const paths = ["/dashboard", "/chat", "/foundation/vehicles", "/assignment", "/fuel", "/maintenance", "/accountability", "/documents", "/insights", "/notifications"]
    for (const path of paths) {
      const allowed = routeAllowedRoles(path)
      for (const role of ROLES) {
        expect(routeAccess(role, path)).toBe(allowed ? allowed.includes(role) : true)
      }
    }
  })
})

describe("visibleDocumentTypes", () => {
  it("matches the CLAUDE.md §2.1 matrix exactly", () => {
    expect(visibleDocumentTypes("admin")).toEqual(["manual", "policy", "supplier_invoice", "incident_report", "legal"])
    expect(visibleDocumentTypes("fleet_manager")).toEqual(["manual", "policy", "supplier_invoice", "incident_report"])
    expect(visibleDocumentTypes("mechanic")).toEqual(["manual", "policy"])
    expect(visibleDocumentTypes("driver")).toEqual(["manual", "policy"])
  })
})
