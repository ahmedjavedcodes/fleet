"use client"

import { useEffect } from "react"
import { TriangleAlert } from "lucide-react"
import { Button } from "@/components/ui/button"

export default function LoginError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    // Details to console only — never a stack trace to users (CLAUDE.md §5.3).
    console.error(error)
  }, [error])

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
      <div className="flex w-full max-w-sm flex-col items-center gap-4 rounded-xl border border-border bg-card p-6 text-center shadow-card">
        <div className="flex size-12 items-center justify-center rounded-xl bg-destructive-soft">
          <TriangleAlert className="size-6 text-destructive" aria-hidden />
        </div>
        <div>
          <p className="text-h3 font-semibold">Something went wrong</p>
          <p className="mt-1 text-sm text-muted-foreground">The sign-in page couldn&apos;t load. Please try again.</p>
        </div>
        <Button onClick={reset}>Retry</Button>
      </div>
    </main>
  )
}
