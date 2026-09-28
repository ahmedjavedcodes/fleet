import { Skeleton } from "@/components/ui/skeleton"

// Shaped like the final form (CLAUDE.md §6) — not a lone spinner.
export default function LoginLoading() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-2">
          <Skeleton className="size-12 rounded-xl" />
          <Skeleton className="h-6 w-28" />
        </div>
        <div className="space-y-5 rounded-xl border border-border bg-card p-6">
          <div className="space-y-2">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-10 w-full" />
          </div>
          <div className="space-y-2">
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-10 w-full" />
          </div>
          <div className="space-y-2">
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-10 w-full" />
          </div>
          <Skeleton className="h-10 w-full" />
        </div>
      </div>
    </main>
  )
}
