"use client"

import { Bell } from "lucide-react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"

// No badge, no count, until the notifications API exists (CLAUDE.md §3,
// §5.5) — never show a fake unread count.
export function NotificationBell() {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" size="icon" aria-label="Notifications">
          <Bell aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72">
        <p className="text-sm font-medium text-foreground">Notifications aren&apos;t available yet</p>
        <p className="mt-1 text-caption text-muted-foreground">This feature is waiting on its backend API.</p>
        <Link href="/notifications" className="mt-3 inline-block text-sm font-medium text-primary-strong hover:underline">
          Go to Notifications
        </Link>
      </PopoverContent>
    </Popover>
  )
}
