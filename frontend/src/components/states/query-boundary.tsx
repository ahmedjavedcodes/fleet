"use client"

import { isApiError, type ApiError } from "@/lib/api/errors"
import { AccessDenied } from "./access-denied"
import { ErrorState } from "./error-state"

// Ties a query to loading/error/(access-denied)/empty/data in one place, so
// every data region handles all five states the same way (plans/03 §5).
// A 403 renders AccessDenied for just this region rather than the generic
// ErrorState — e.g. one dashboard KPI tile 403ing shouldn't take down the
// rest of the page (plans/04 §2).
export function QueryRegion<T>({
  query,
  skeleton,
  empty,
  isEmpty,
  areaLabel,
  children,
}: {
  query: { data: T | undefined; isPending: boolean; error: unknown; refetch: () => unknown }
  skeleton: React.ReactNode
  empty?: React.ReactNode
  isEmpty?: (data: T) => boolean
  areaLabel?: string
  children: (data: T) => React.ReactNode
}) {
  if (query.isPending) return <>{skeleton}</>

  if (query.error) {
    const apiError: ApiError = isApiError(query.error) ? query.error : { kind: "network" }
    if (apiError.kind === "forbidden") {
      return <AccessDenied area={areaLabel ?? "this data"} allowedRoles={null} />
    }
    return <ErrorState error={apiError} onRetry={() => void query.refetch()} />
  }

  const data = query.data as T
  if (empty && isEmpty?.(data)) return <>{empty}</>

  return <>{children(data)}</>
}
