"use client"

import { useState } from "react"
import { Check, ClipboardList, Fuel, MapPin, Route, Search, ShieldAlert, Sparkles, TriangleAlert, Wrench } from "lucide-react"
import type { LucideIcon } from "lucide-react"
import type { AgentKey, HitlState } from "@/lib/schemas/chat"
import { cn } from "@/lib/utils"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { IconTile } from "@/components/primitives/icon-tile"
import { Textarea } from "@/components/ui/textarea"

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
export function AgentActivity({ steps }: { steps: ActivityStep[] }) {
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
}

// A pending action awaiting a human decision. Never auto-approved — every
// path here requires an explicit click (plans/07 §3, CLAUDE.md §4.5).
export function ApprovalCard({
  hitlState,
  onApprove,
  onModify,
  onReject,
}: {
  hitlState: HitlState
  onApprove: () => void
  onModify: (notes: string) => void
  onReject: () => void
}) {
  const [modifying, setModifying] = useState(false)
  const [notes, setNotes] = useState("")
  const [confirmingReject, setConfirmingReject] = useState(false)

  return (
    <div className="space-y-3 rounded-xl border border-warning-border bg-warning-soft p-4">
      <p className="text-sm font-medium text-foreground">{hitlState.approval_prompt ?? "This action needs your approval."}</p>
      <p className="text-caption text-muted-foreground">{hitlState.tool_name ?? hitlState.agent_name}</p>

      {modifying ? (
        <div className="space-y-2">
          <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Describe the change…" rows={2} />
          <div className="flex gap-2">
            <Button size="sm" onClick={() => onModify(notes)} disabled={notes.trim() === ""}>
              Submit change
            </Button>
            <Button size="sm" variant="outline" onClick={() => setModifying(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={onApprove}>
            Approve
          </Button>
          <Button size="sm" variant="outline" onClick={() => setModifying(true)}>
            Modify
          </Button>
          <Button size="sm" variant="outline" onClick={() => setConfirmingReject(true)}>
            Reject
          </Button>
        </div>
      )}

      <AlertDialog open={confirmingReject} onOpenChange={setConfirmingReject}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reject this action?</AlertDialogTitle>
            <AlertDialogDescription>The agent will stop and report back instead of proceeding.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={onReject}>Reject</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

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
