"use client"

import { useState } from "react"
import { Menu, Truck } from "lucide-react"
import { APP_NAME } from "@/lib/brand"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { SidebarNav } from "./sidebar-nav"
import { UserMenu } from "./user-menu"

// Below `lg`, the sidebar is hidden and this hamburger-triggered drawer
// takes over (plans/03 §3). Lives in the topbar (its trigger) but renders
// the same SidebarNav the desktop Sidebar uses, always expanded.
export function MobileSidebar() {
  const [open, setOpen] = useState(false)

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button type="button" variant="ghost" size="icon" className="lg:hidden" aria-label="Open menu">
          <Menu aria-hidden />
        </Button>
      </SheetTrigger>
      <SheetContent side="left" className="flex w-72 flex-col gap-0">
        <SheetHeader className="border-b border-border">
          <SheetTitle className="flex items-center gap-2">
            <span className="flex size-9 items-center justify-center rounded-md bg-primary-soft" aria-hidden>
              <Truck className="size-5 text-primary" />
            </span>
            {APP_NAME}
          </SheetTitle>
        </SheetHeader>
        <SidebarNav collapsed={false} onNavigate={() => setOpen(false)} />
        <div className="border-t border-border p-3">
          <UserMenu />
        </div>
      </SheetContent>
    </Sheet>
  )
}
