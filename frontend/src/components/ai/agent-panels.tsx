"use client"

import { memo } from "react"
import { Check, ClipboardList, Fuel, MapPin, Route, Search, ShieldAlert, Sparkles, TriangleAlert, Wrench } from "lucide-react"
import type { LucideIcon } from "lucide-react"
import type { AgentKey } from "@/lib/schemas/chat"
import { cn } from "@/lib/utils"
import { IconTile } from "@/components/primitives/icon-tile"

// ApprovalCard lives in ./approval-card (loaded lazily by the chat page).

const AGENT_ICON: Record<AgentKey, LucideIcon> = {
  foundation: MapPin,
  fuel: Fuel,
  maintenance: Wrench,
  accountability: ShieldAlert,
  insights: ClipboardList,
  assignment: Route,
  search_documents: Search,
  update_memory: ClipboardList,
  orchestrator: Sparkles,
}

export type ActivityStep = { agent: AgentKey; step: string; done: boolean }

// A step row per agent invocation, with a pulsing active indicator that
// honors `prefers-reduced-motion` (plans/07 §3). Step text is rendered
// exactly as the backend sends it — never reworded here.
export const AgentActivity = memo(function AgentActivity({ steps }: { steps: ActivityStep[] }) {
  return (
    <ol className="space-y-1.5">
      {steps.map((s, i) => {
        const Icon = AGENT_ICON[s.agent]
        return (
          <li key={i} className="flex items-center gap-2 text-caption">
            <IconTile icon={Icon} tone="muted" size="sm" />
            <span className={cn(s.done ? "text-foreground" : "text-muted-foreground")}>{s.step}</span>
            {s.done ? (
              <Check className="size-3.5 text-success" aria-hidden />
            ) : (
              <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-primary motion-reduce:animate-none" />
            )}
          </li>
        )
      })}
    </ol>
  )
})

// A halted run — a warning, not an error (plans/07 §3): the agent stopped
// itself, nothing crashed.
export function HaltedCard({ reason }: { reason: string }) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-warning-border bg-warning-soft p-3">
      <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning-icon" aria-hidden />
      <p className="text-sm text-foreground">{reason}</p>
    </div>
  )
}
