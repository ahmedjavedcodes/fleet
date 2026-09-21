import { Skeleton } from "@/components/ui/Skeleton";

export default function DashboardLoading() {
  return (
    <main className="min-h-screen p-8">
      <Skeleton className="h-8 w-56" />
      <div className="mt-8 grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <Skeleton className="mt-8 h-64 w-full" />
    </main>
  );
}
