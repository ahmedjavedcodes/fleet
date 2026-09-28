import { QueryCache, QueryClient } from "@tanstack/react-query"
import { isApiError } from "@/lib/api/errors"
import { safeNextPath } from "@/lib/auth/safe-next-path"

// CLAUDE.md §5.1 / plans/02 §7: never retry a 4xx (401/403/404/409/422/429),
// retry network/5xx up to 2× with backoff, and redirect once on a 401 from
// any query (mutations surface their own 401 through the caller's error
// state instead — react-query only auto-redirects for *queries*).

function redirectToLogin() {
  if (typeof window === "undefined") return
  if (window.location.pathname === "/login") return
  const next = safeNextPath(window.location.pathname + window.location.search)
  window.location.href = next ? `/login?next=${encodeURIComponent(next)}` : "/login"
}

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: true,
        retry: (failureCount, error) => {
          if (isApiError(error)) {
            // "network" and "schema" have no HTTP status: a dropped
            // connection is worth retrying, a contract mismatch is not.
            if (error.kind === "schema") return false
            if (error.kind !== "network" && error.status >= 400 && error.status < 500) return false
          }
          return failureCount < 2
        },
        retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 10_000),
      },
    },
    queryCache: new QueryCache({
      onError: (error) => {
        if (isApiError(error) && error.kind === "unauthorized") {
          redirectToLogin()
        }
      },
    }),
  })
}
