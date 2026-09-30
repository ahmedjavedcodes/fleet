"use client"

import { usePathname } from "next/navigation"
import { routeLabel } from "@/lib/route-labels"
import { Separator } from "@/components/ui/separator"
import { MobileSidebar } from "./mobile-sidebar"
import { NotificationBell } from "./notification-bell"
import { useTopbarSlots } from "./topbar-slots"

// Left to right: hamburger (<lg only), breadcrumbs, status pill, page
// actions, notification bell (plans/03 §4). The user menu lives on the
// sidebar's user card, not here (CLAUDE.md §3).
export function Topbar() {
  const pathname = usePathname()
  const { crumbs, status, actions } = useTopbarSlots()

  return (
    <header className="flex h-(--topbar-height) shrink-0 items-center gap-3 rounded-xl border border-border bg-card px-4 py-3">
      <MobileSidebar />

      <div className="min-w-0 flex-1">
        {crumbs ?? <span className="truncate text-sm font-semibold text-foreground">{routeLabel(pathname)}</span>}
      </div>

      {status ? <div className="hidden shrink-0 sm:block">{status}</div> : null}

      <div className="flex shrink-0 items-center gap-2">
        {actions ? (
          <>
            {actions}
            <Separator orientation="vertical" className="h-6" />
          </>
        ) : null}
        <NotificationBell />
      </div>
    </header>
  )
}
