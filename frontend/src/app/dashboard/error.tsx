"use client";

import { ErrorBanner } from "@/components/ui/ErrorBanner";

export default function DashboardError({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <main className="min-h-screen p-8">
      <ErrorBanner message={error.message || "Failed to load the dashboard."} onRetry={reset} />
    </main>
  );
}
