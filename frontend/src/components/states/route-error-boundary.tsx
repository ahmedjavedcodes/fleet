"use client"

import { useEffect } from "react"
import { TriangleAlert } from "lucide-react"
import { Button } from "@/components/ui/button"
import { IconTile } from "@/components/primitives/icon-tile"

// Every route's error.tsx re-exports this directly (`export { RouteErrorBoundary
// as default } from "@/components/states/route-error-boundary"`) — Next
// requires error.tsx to be co-located per route segment, but the fallback
// itself is identical everywhere, so only the file, not the implementation,
// repeats. This is the crash boundary for a thrown render error, distinct
// from ErrorState (which renders a *handled* ApiError from a query).
export function RouteErrorBoundary({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    // Details to console only — never a stack trace to users (CLAUDE.md §5.3).
    console.error(error)
  }, [error])

  return (
    <div
      role="alert"
      className="flex min-h-[50vh] flex-col items-center justify-center gap-4 rounded-xl border border-border bg-card p-8 text-center"
    >
      <IconTile icon={TriangleAlert} tone="destructive" size="lg" />
      <div>
        <p className="text-h3 font-semibold text-foreground">Something went wrong</p>
        <p className="mt-1 text-sm text-muted-foreground">This page couldn&apos;t load. Please try again.</p>
      </div>
      <Button onClick={reset}>Retry</Button>
    </div>
  )
}
