import { QueryClient } from "@tanstack/react-query"

// Minimal defaults for phase 01. Phase 02 adds the 4xx-aware retry policy and the
// global 401 redirect once `ApiError` exists (plans/02-auth-bff-and-api-layer.md §7).
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: true,
      },
    },
  })
}
