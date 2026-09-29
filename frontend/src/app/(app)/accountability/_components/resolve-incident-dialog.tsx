"use client"

import { useState } from "react"
import { toast } from "sonner"
import { useUpdateIncidentResolution } from "@/lib/api/incidents"
import type { IncidentLog } from "@/lib/schemas/incident"
import type { IncidentResolutionStatus } from "@/lib/schemas/enums"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Field, FieldLabel } from "@/components/ui/field"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"

const STATUSES: IncidentResolutionStatus[] = ["open", "investigating", "resolved", "closed"]

export function ResolveIncidentDialog({ incident, onOpenChange }: { incident: IncidentLog; onOpenChange: (open: boolean) => void }) {
  const [status, setStatus] = useState<IncidentResolutionStatus>(incident.resolution_status)
  const [notes, setNotes] = useState(incident.resolution_notes ?? "")
  const mutation = useUpdateIncidentResolution(incident.id)

  function submit() {
    mutation.mutate(
      { resolution_status: status, resolution_notes: notes || undefined },
      {
        onSuccess: () => {
          toast.success("Incident updated")
          onOpenChange(false)
        },
        onError: () => toast.error("Couldn't update this incident."),
      }
    )
  }

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Update resolution</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <Field>
            <FieldLabel htmlFor="resolution_status">Status</FieldLabel>
            <Select value={status} onValueChange={(v) => setStatus(v as IncidentResolutionStatus)}>
              <SelectTrigger id="resolution_status" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STATUSES.map((s) => (
                  <SelectItem key={s} value={s}>
                    {s[0]!.toUpperCase() + s.slice(1)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field>
            <FieldLabel htmlFor="resolution_notes">Notes</FieldLabel>
            <Textarea id="resolution_notes" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </Field>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={mutation.isPending}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
