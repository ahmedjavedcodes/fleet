"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import { routeAccess } from "@/lib/rbac"
import { cn } from "@/lib/utils"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { NAV_GROUPS } from "./nav-items"

// Shared between the desktop <Sidebar> and the mobile Sheet drawer.
// Filtered by routeAccess (rbac.ts §2.1) — a group with no visible items is
// hidden entirely, including its group label (plans/03 §3).
export function SidebarNav({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const pathname = usePathname()
  const { role, isPending } = useCurrentUser()

  // Skeleton rows, not the real list, while the role is unknown — nav items
  // must never flash in and then get filtered out (plans/03 §3).
  if (isPending || !role) {
    return (
      <nav aria-label="Loading navigation" className="flex-1 space-y-1.5 overflow-y-auto p-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-9 w-full rounded-lg" />
        ))}
      </nav>
    )
  }

  return (
    <nav aria-label="Primary" className="flex-1 space-y-4 overflow-y-auto p-3">
      {NAV_GROUPS.map((group) => {
        const items = group.items.filter((item) => routeAccess(role, item.href))
        if (items.length === 0) return null

        return (
          <div key={group.label}>
            {!collapsed && <p className="mb-1 px-2 text-caption font-medium text-muted-foreground">{group.label}</p>}
            <ul className="space-y-0.5">
              {items.map((item) => {
                const isActive = pathname === item.href || pathname.startsWith(`${item.href}/`)
                const link = (
                  <Link
                    href={item.href}
                    prefetch
                    onClick={onNavigate}
                    aria-current={isActive ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium transition duration-150 ease-standard",
                      "focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                      collapsed && "justify-center",
                      isActive ? "bg-primary-soft text-primary-strong" : "text-foreground hover:bg-muted"
                    )}
                  >
                    <item.icon
                      className={cn("size-5 shrink-0", isActive ? "text-primary" : "text-muted-foreground")}
                      aria-hidden
                    />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                  </Link>
                )

                if (!collapsed) return <li key={item.href}>{link}</li>

                return (
                  <li key={item.href}>
                    <Tooltip>
                      <TooltipTrigger asChild>{link}</TooltipTrigger>
                      <TooltipContent side="right">{item.label}</TooltipContent>
                    </Tooltip>
                  </li>
                )
              })}
            </ul>
          </div>
        )
      })}
    </nav>
  )
}
