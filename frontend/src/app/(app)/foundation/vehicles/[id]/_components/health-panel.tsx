"use client"

import { HeartPulse } from "lucide-react"
import Link from "next/link"
import { useFleetHealth } from "@/lib/api/dashboard"
import { formatInt } from "@/lib/api/decimal"
import { healthScoreLabel } from "@/lib/health-score"
import { HealthGauge } from "@/components/charts/health-gauge"
import { InnerCard } from "@/components/primitives/inner-card"
import { SectionPanel } from "@/components/primitives/section-panel"
import { StatusPill } from "@/components/primitives/status-pill"
import { EmptyState } from "@/components/states/empty-state"
import { SkeletonPanel } from "@/components/states/page-skeleton"
import { QueryRegion } from "@/components/states/query-boundary"

const SIGNALS = [
  { key: "compliance", title: "Compliance", detail: "Service rules met on schedule", href: null },
  { key: "incidents", title: "Incidents", detail: "Incidents in the last 90 days", href: "/accountability" },
  { key: "maintenance_currency", title: "Maintenance", detail: "Overdue or upcoming service", href: "/maintenance" },
  { key: "fuel_efficiency", title: "Fuel efficiency", detail: "Cost per km vs the previous period", href: "/fuel" },
] as const

// A/FM only — dashboard/fleet-health is gated (plans/05 §2.6). The page
// only mounts this component for those roles, so calling the hook here is
// always allowed.
export function HealthPanel({ vehicleId }: { vehicleId: string }) {
  const query = useFleetHealth()

  return (
    <SectionPanel icon={HeartPulse} title="Vehicle Health Score">
      <QueryRegion
        query={query}
        skeleton={<SkeletonPanel />}
        areaLabel="the vehicle health score"
      >
        {(rows) => {
          const entry = rows.find((r) => r.vehicle_id === vehicleId)
          if (!entry) {
            return <EmptyState icon={HeartPulse} title="Not scored" description="Health isn't scored for retired vehicles." />
          }
          const { label, tone } = healthScoreLabel(entry.health_score)
          return (
            <div className="space-y-4">
              <div className="flex flex-col items-center gap-2">
                <HealthGauge score={entry.health_score} size="lg" />
                <StatusPill tone={tone}>{label}</StatusPill>
              </div>
              <div className="space-y-2">
                {SIGNALS.map((s) => {
                  const value = entry.signals[s.key]
                  const row = (
                    <InnerCard key={s.key} className="flex items-center justify-between p-3">
                      <div>
                        <p className="text-sm font-medium text-foreground">{s.title}</p>
                        <p className="text-caption text-muted-foreground">{s.detail}</p>
                      </div>
                      {value === null ? (
                        <span className="text-sm text-muted-foreground">n/a</span>
                      ) : (
                        <span className="text-sm font-semibold text-foreground">{formatInt(value)}</span>
                      )}
                    </InnerCard>
                  )
                  return s.href ? (
                    <Link key={s.key} href={s.href} className="block rounded-xl focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
                      {row}
                    </Link>
                  ) : (
                    row
                  )
                })}
              </div>
            </div>
          )
        }}
      </QueryRegion>
    </SectionPanel>
  )
}
