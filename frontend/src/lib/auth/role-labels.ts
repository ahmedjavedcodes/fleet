import type { UserRole } from "@/lib/schemas/enums"

// The only place these labels are spelled out (topbar user menu, role
// badges, access-denied hints — CLAUDE.md §3).
export const roleLabels: Record<UserRole, string> = {
  admin: "Admin",
  fleet_manager: "Fleet Manager",
  mechanic: "Mechanic",
  driver: "Driver",
}

export function roleLabel(role: UserRole): string {
  return roleLabels[role]
}
