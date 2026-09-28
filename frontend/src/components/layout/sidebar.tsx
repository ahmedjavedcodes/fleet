"use client"

import { useEffect, useState } from "react"
import { PanelLeft, Truck } from "lucide-react"
import { APP_NAME } from "@/lib/brand"
import { useMediaQuery } from "@/lib/use-media-query"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { SidebarNav } from "./sidebar-nav"
import { UserMenu } from "./user-menu"

// A UI preference only (no token or org data) — CLAUDE.md §4.5 allows
// localStorage for this.
const COLLAPSE_KEY = "fleetops:sidebar-collapsed"

// The persistent desktop sidebar (plans/03 §3): expanded at `xl`+,
// icon-only at `lg`, hidden below `lg` (see MobileSidebar for the Sheet
// drawer). The collapse toggle can force icon-only even at `xl`+.
//
// `collapsed` combines both: it must be a single JS boolean, not "shrink
// the container via a CSS breakpoint but hide children via JS state" — the
// two would disagree between `lg` and `xl` (a narrow container with full
// label text still rendered inside it, overflowing). useMediaQuery gives an
// accurate viewport-derived default that the manual toggle then overrides.
export function Sidebar() {
  const isXlUp = useMediaQuery("(min-width: 1280px)")
  const [manuallyCollapsed, setManuallyCollapsed] = useState(false)
  const collapsed = manuallyCollapsed || !isXlUp

  useEffect(() => {
    try {
      if (window.localStorage.getItem(COLLAPSE_KEY) === "1") setManuallyCollapsed(true)
    } catch {
      // Private browsing / blocked storage — default to expanded.
    }
  }, [])

  function toggleCollapsed() {
    setManuallyCollapsed((prev) => {
      const next = !prev
      try {
        window.localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0")
      } catch {
        // Ignore — this is a UI preference only.
      }
      return next
    })
  }

  return (
    <aside
      className={cn(
        "hidden shrink-0 flex-col rounded-xl border border-sidebar-border bg-sidebar lg:flex",
        collapsed ? "w-20" : "w-72"
      )}
    >
      <div className={cn("flex items-center gap-2 border-b border-sidebar-border p-3", collapsed && "justify-center")}>
        <span
          className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary-soft"
          aria-label={collapsed ? APP_NAME : undefined}
          aria-hidden={collapsed ? undefined : true}
        >
          <Truck className="size-5 text-primary" aria-hidden />
        </span>
        {!collapsed && <span className="truncate text-h3 font-semibold text-sidebar-foreground">{APP_NAME}</span>}
        {!collapsed && (
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="ml-auto"
            aria-label="Collapse sidebar"
            onClick={toggleCollapsed}
          >
            <PanelLeft aria-hidden />
          </Button>
        )}
      </div>
      {collapsed && (
        <div className="flex justify-center border-b border-sidebar-border p-2">
          <Button type="button" variant="ghost" size="icon-sm" aria-label="Expand sidebar" onClick={toggleCollapsed}>
            <PanelLeft aria-hidden />
          </Button>
        </div>
      )}
      <SidebarNav collapsed={collapsed} />
      <div className="border-t border-sidebar-border p-3">
        <UserMenu collapsed={collapsed} />
      </div>
    </aside>
  )
}
