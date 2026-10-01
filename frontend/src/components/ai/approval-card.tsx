"use client"

import { useState } from "react"
import type { HitlState } from "@/lib/schemas/chat"
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
import { Textarea } from "@/components/ui/textarea"

// Its own module so the chat page can load it (and Radix AlertDialog with it) only when an
// approval is actually pending, instead of shipping it with every chat visit.
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
      {hitlState.summary && hitlState.summary.length > 0 ? (
        <dl aria-label="Details to be recorded" className="grid grid-cols-1 gap-x-4 gap-y-1.5 rounded-lg border border-warning-border bg-card p-3 text-sm sm:grid-cols-[max-content_1fr]">
          {hitlState.summary.map((row) => (
            <div key={row.label} className="contents">
              <dt className="text-muted-foreground">{row.label}</dt>
              <dd className="font-medium break-words text-foreground">{row.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}

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

export default ApprovalCard
