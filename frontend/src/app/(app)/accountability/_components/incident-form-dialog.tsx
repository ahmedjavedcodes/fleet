"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useEffect } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { useCreateIncident } from "@/lib/api/incidents"
import { useVehicles } from "@/lib/api/vehicles"
import { isApiError } from "@/lib/api/errors"
import { INCIDENT_TYPE_LABELS } from "@/lib/enum-labels"
import { incidentLogCreateSchema, type IncidentLogCreate } from "@/lib/schemas/incident"
import type { IncidentSeverity, IncidentType } from "@/lib/schemas/enums"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"

const TYPES = Object.keys(INCIDENT_TYPE_LABELS) as IncidentType[]
const SEVERITIES: IncidentSeverity[] = ["minor", "moderate", "severe", "critical"]

export function IncidentFormDialog({
  open,
  onOpenChange,
  defaultVehicleId,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  defaultVehicleId?: string
}) {
  const vehiclesQuery = useVehicles()
  const createMutation = useCreateIncident()
  const {
    register,
    handleSubmit,
    reset,
    setError,
    setValue,
    watch,
    formState: { errors },
  } = useForm<IncidentLogCreate>({
    resolver: zodResolver(incidentLogCreateSchema),
    defaultValues: {
      vehicle_id: defaultVehicleId ?? "",
      incident_type: "damage",
      date: new Date().toISOString().slice(0, 10),
      severity: "minor",
      description: "",
    },
  })

  useEffect(() => {
    if (open) {
      reset({ vehicle_id: defaultVehicleId ?? "", incident_type: "damage", date: new Date().toISOString().slice(0, 10), severity: "minor", description: "" })
    }
  }, [open, defaultVehicleId, reset])

  function onSubmit(values: IncidentLogCreate) {
    createMutation.mutate(values, {
      onSuccess: () => {
        toast.success("Incident reported")
        onOpenChange(false)
      },
      onError: (error) => {
        if (!isApiError(error)) return
        if (error.kind === "validation") {
          for (const [field, message] of Object.entries(error.fieldErrors)) {
            setError(field as keyof IncidentLogCreate, { message })
          }
          return
        }
        toast.error("message" in error ? error.message : "Something went wrong. Please try again.")
      },
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Report incident</DialogTitle>
        </DialogHeader>
        <form onSubmit={(e) => void handleSubmit(onSubmit)(e)} noValidate className="space-y-4">
          <FieldGroup>
            <Field data-invalid={Boolean(errors.vehicle_id)}>
              <FieldLabel htmlFor="vehicle_id">Vehicle</FieldLabel>
              <Select value={watch("vehicle_id")} onValueChange={(v) => setValue("vehicle_id", v)}>
                <SelectTrigger id="vehicle_id" className="w-full">
                  <SelectValue placeholder="Select a vehicle" />
                </SelectTrigger>
                <SelectContent>
                  {(vehiclesQuery.data ?? []).map((v) => (
                    <SelectItem key={v.id} value={v.id}>
                      {v.plate_number}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FieldError errors={[errors.vehicle_id]} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field>
                <FieldLabel htmlFor="incident_type">Type</FieldLabel>
                <Select value={watch("incident_type")} onValueChange={(v) => setValue("incident_type", v as IncidentType)}>
                  <SelectTrigger id="incident_type" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TYPES.map((t) => (
                      <SelectItem key={t} value={t}>
                        {INCIDENT_TYPE_LABELS[t]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field>
                <FieldLabel htmlFor="severity">Severity</FieldLabel>
                <Select value={watch("severity")} onValueChange={(v) => setValue("severity", v as IncidentSeverity)}>
                  <SelectTrigger id="severity" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SEVERITIES.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s[0]!.toUpperCase() + s.slice(1)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            </div>
            <Field data-invalid={Boolean(errors.date)}>
              <FieldLabel htmlFor="date">Date</FieldLabel>
              <Input id="date" type="date" {...register("date")} />
              <FieldError errors={[errors.date]} />
            </Field>
            <Field data-invalid={Boolean(errors.description)}>
              <FieldLabel htmlFor="description">Description</FieldLabel>
              <Textarea id="description" rows={3} {...register("description")} />
              <FieldError errors={[errors.description]} />
            </Field>
          </FieldGroup>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={createMutation.isPending}>
              Report incident
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
