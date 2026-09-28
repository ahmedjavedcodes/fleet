import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query"
import { getServerMe } from "@/lib/auth/session"
import { meKeys } from "@/lib/query/keys"
import { RouteGuard } from "@/components/layout/route-guard"
import { Sidebar } from "@/components/layout/sidebar"
import { Topbar } from "@/components/layout/topbar"
import { TopbarSlotsProvider } from "@/components/layout/topbar-slots"

// The persistent authenticated shell (plans/03 §1). A Server Component: it
// prefetches /auth/me into a HydrationBoundary so the sidebar's user card
// and RouteGuard's role check paint without a loading flash, using the same
// query the client-side useCurrentUser() hook reads (meKeys.current()).
// Never re-mounts on navigation — only {children} swaps.
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const me = await getServerMe()
  const queryClient = new QueryClient()
  if (me) {
    queryClient.setQueryData(meKeys.current(), me)
  }

  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <a
        href="#content"
        className="sr-only focus-visible:not-sr-only focus-visible:fixed focus-visible:top-3 focus-visible:left-3 focus-visible:z-50 focus-visible:rounded-lg focus-visible:bg-primary-strong focus-visible:px-4 focus-visible:py-2 focus-visible:text-sm focus-visible:font-medium focus-visible:text-primary-foreground"
      >
        Skip to content
      </a>
      <TopbarSlotsProvider>
        <div className="flex min-h-screen gap-4 bg-background p-4">
          <Sidebar />
          <div className="flex min-w-0 flex-1 flex-col gap-4">
            <Topbar />
            <main id="content" className="min-w-0 flex-1">
              <RouteGuard>{children}</RouteGuard>
            </main>
          </div>
        </div>
      </TopbarSlotsProvider>
    </HydrationBoundary>
  )
}
