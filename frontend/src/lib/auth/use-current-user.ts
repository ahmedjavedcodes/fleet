"use client"

import { useQuery } from "@tanstack/react-query"
import { getMe } from "@/lib/api/auth"
import { meKeys } from "@/lib/query/keys"

// The one client-side source of the signed-in user, role and org (CLAUDE.md
// §3: never decode the JWT — this is GET /auth/me, always). Also refetches
// on window focus (the query-client default) so a role change the backend
// re-reads on every request shows up here without a re-login.
export function useCurrentUser() {
  const query = useQuery({
    queryKey: meKeys.current(),
    queryFn: getMe,
  })

  return {
    ...query,
    user: query.data?.user ?? null,
    organization: query.data?.organization ?? null,
    driverProfile: query.data?.driver_profile ?? null,
    role: query.data?.user.role ?? null,
  }
}
