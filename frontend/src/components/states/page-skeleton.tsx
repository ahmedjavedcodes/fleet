import { Skeleton } from "@/components/ui/skeleton"

// Skeletons shaped like the final content (CLAUDE.md §6) — never a lone
// spinner for page content. Used by loading.tsx and by a data region while
// its query isPending.

export function SkeletonKpiGrid({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="space-y-3 rounded-xl border border-border bg-card p-5">
          <Skeleton className="size-9 rounded-md" />
          <Skeleton className="h-7 w-16" />
        </div>
      ))}
    </div>
  )
}

export function SkeletonTable({ rows = 5, columns = 4 }: { rows?: number; columns?: number }) {
  return (
    <div className="space-y-3 rounded-xl border border-border bg-card p-4">
      <Skeleton className="h-4 w-full" />
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-4">
          {Array.from({ length: columns }).map((_, j) => (
            <Skeleton key={j} className="h-8 flex-1" />
          ))}
        </div>
      ))}
    </div>
  )
}

export function SkeletonChart() {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <Skeleton className="mb-4 h-5 w-40" />
      <Skeleton className="h-48 w-full" />
    </div>
  )
}

export function SkeletonPanel() {
  return (
    <div className="space-y-3 rounded-xl bg-panel p-6">
      <Skeleton className="h-5 w-32" />
      <Skeleton className="h-24 w-full rounded-lg" />
      <Skeleton className="h-24 w-full rounded-lg" />
    </div>
  )
}

export function PageSkeleton() {
  return (
    <div className="space-y-6 p-1">
      <Skeleton className="h-6 w-48" />
      <SkeletonKpiGrid />
      <div className="grid gap-4 lg:grid-cols-2">
        <SkeletonChart />
        <SkeletonPanel />
      </div>
    </div>
  )
}
