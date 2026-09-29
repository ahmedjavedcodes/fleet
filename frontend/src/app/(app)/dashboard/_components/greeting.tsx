"use client"

import { useCurrentUser } from "@/lib/auth/use-current-user"
import { Skeleton } from "@/components/ui/skeleton"

function timeOfDayGreeting(): string {
  const hour = new Date().getHours()
  if (hour < 12) return "Good morning"
  if (hour < 18) return "Good afternoon"
  return "Good evening"
}

// "Good morning, {first name}" with organization.name muted underneath
// (plans/04 §1) — time-of-day aware rather than a hardcoded "morning", so
// it doesn't read oddly in the afternoon.
export function Greeting() {
  const { user, organization, isPending } = useCurrentUser()

  if (isPending || !user) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-4 w-40" />
      </div>
    )
  }

  const firstName = user.full_name.trim().split(/\s+/)[0]

  return (
    <div>
      <h1 className="text-h1 text-foreground">
        {timeOfDayGreeting()}, {firstName}
      </h1>
      {organization ? <p className="text-sm text-muted-foreground">{organization.name}</p> : null}
    </div>
  )
}
