import { TriangleAlert } from "lucide-react"
import { genericErrorMessage, type ApiError } from "@/lib/api/errors"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { IconTile } from "@/components/primitives/icon-tile"

// A *handled* ApiError from a query (distinct from RouteErrorBoundary,
// which catches a thrown render error). The body text comes from
// genericErrorMessage (lib/api/errors.ts), which already carries the
// per-kind copy (404, 409, 429, 503, schema, …) — this component only
// varies the title and whether Retry makes sense (plans/03 §5).
const TITLES: Record<ApiError["kind"], string> = {
  unauthorized: "Session expired",
  forbidden: "Access denied",
  not_found: "Not found",
  conflict: "Out of date",
  bad_request: "Can't complete this",
  validation: "Check the form",
  rate_limited: "Slow down",
  payload_too_large: "File too large",
  unsupported_media: "Unsupported file",
  unavailable: "Temporarily unavailable",
  server: "Something went wrong",
  network: "Connection lost",
  schema: "Unexpected response",
}

export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: ApiError
  onRetry?: () => void
  className?: string
}) {
  // A 403 is a permissions fact, never retried — callers should generally
  // route it to AccessDenied instead, but this is a safe fallback if one
  // reaches here directly.
  const canRetry = Boolean(onRetry) && error.kind !== "forbidden"

  return (
    <div
      role="alert"
      className={cn("flex flex-col items-center gap-3 rounded-xl border border-border bg-card p-8 text-center", className)}
    >
      <IconTile icon={TriangleAlert} tone="destructive" size="lg" />
      <div>
        <p className="text-h3 font-semibold text-foreground">{TITLES[error.kind]}</p>
        <p className="mt-1 text-sm text-muted-foreground">{genericErrorMessage(error)}</p>
      </div>
      {canRetry ? (
        <Button variant="outline" onClick={onRetry}>
          Retry
        </Button>
      ) : null}
    </div>
  )
}
