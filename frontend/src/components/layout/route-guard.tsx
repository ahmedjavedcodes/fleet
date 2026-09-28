"use client"

import { usePathname } from "next/navigation"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import { routeAccess, routeAllowedRoles } from "@/lib/rbac"
import { routeLabel } from "@/lib/route-labels"
import { AccessDenied } from "@/components/states/access-denied"
import { PageSkeleton } from "@/components/states/page-skeleton"

// Wraps every page in (app)/layout.tsx (plans/03 §5): renders AccessDenied
// when the current role can't open this route, so a page never needs its
// own role check just to render. This is UX only — the backend's 403 on
// each actual request is the real enforcement (CLAUDE.md non-negotiable #3);
// QueryRegion handles that fallback per data region.
export function RouteGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const { role, isPending } = useCurrentUser()

  if (isPending) return <PageSkeleton />
  // No role means the session query hasn't resolved yet or failed — the
  // query client's global 401 handling (lib/query/client.ts) already
  // redirects to /login in that case, so there's nothing useful to render.
  if (!role) return null

  if (!routeAccess(role, pathname)) {
    return <AccessDenied area={routeLabel(pathname)} allowedRoles={routeAllowedRoles(pathname)} />
  }

  return <>{children}</>
}
