"use client"

import { useCurrentUser } from "@/lib/auth/use-current-user"
import { PageHeader } from "@/components/layout/page-header"
import { PageSkeleton } from "@/components/states/page-skeleton"
import { AdminDashboard } from "./_components/admin-dashboard"
import { DriverDashboard } from "./_components/driver-dashboard"
import { MechanicDashboard } from "./_components/mechanic-dashboard"

// Never call /dashboard/* for mechanic or driver — those endpoints 403 for
// them (CLAUDE.md §2.2); each variant below composes only the endpoints its
// role can actually read.
export default function DashboardPage() {
  const { role, isPending } = useCurrentUser()

  if (isPending || !role) {
    return (
      <>
        <PageHeader crumbs={[{ label: "Overview" }]} />
        <PageSkeleton />
      </>
    )
  }

  switch (role) {
    case "admin":
    case "fleet_manager":
      return <AdminDashboard />
    case "mechanic":
      return <MechanicDashboard />
    case "driver":
      return <DriverDashboard />
  }
}
