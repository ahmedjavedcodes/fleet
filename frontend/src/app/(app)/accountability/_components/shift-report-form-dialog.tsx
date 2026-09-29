"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useEffect } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { useCreateDriverReport } from "@/lib/api/driver-reports"
import { useVehicles } from "@/lib/api/vehicles"
import { isApiError } from "@/lib/api/errors"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import { driverReportCreateSchema, type DriverReportCreate } from "@/lib/schemas/driver-report"
import type { VehicleCondition } from "@/lib/schemas/enums"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"

export function ShiftReportFormDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { driverProfile } = useCurrentUser()
  const vehiclesQuery = useVehicles()
  const createMutation = useCreateDriverReport()
  const {
    register,
    handleSubmit,
    reset,
    setError,
    setValue,
    watch,
    formState: { errors },
  } = useForm<DriverReportCreate>({
    resolver: zodResolver(driverReportCreateSchema),
    defaultValues: { driver_id: driverProfile?.id ?? "", vehicle_id: "", shift_date: new Date().toISOString().slice(0, 10), vehicle_condition: "good" },
  })

  useEffect(() => {
    if (open) reset({ driver_id: driverProfile?.id ?? "", vehicle_id: "", shift_date: new Date().toISOString().slice(0, 10), vehicle_condition: "good" })
  }, [open, driverProfile, reset])

  function onSubmit(values: DriverReportCreate) {
    createMutation.mutate(values, {
      onSuccess: () => {
        toast.success("Shift report submitted")
        onOpenChange(false)
      },
      onError: (error) => {
        if (!isApiError(error)) return
        if (error.kind === "validation") {
          for (const [field, message] of Object.entries(error.fieldErrors)) {
            setError(field as keyof DriverReportCreate, { message })
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
          <DialogTitle>Submit shift report</DialogTitle>
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
              <Field data-invalid={Boolean(errors.shift_date)}>
                <FieldLabel htmlFor="shift_date">Shift date</FieldLabel>
                <Input id="shift_date" type="date" {...register("shift_date")} />
                <FieldError errors={[errors.shift_date]} />
              </Field>
              <Field>
                <FieldLabel htmlFor="vehicle_condition">Vehicle condition</FieldLabel>
                <Select value={watch("vehicle_condition")} onValueChange={(v) => setValue("vehicle_condition", v as VehicleCondition)}>
                  <SelectTrigger id="vehicle_condition" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="good">Good</SelectItem>
                    <SelectItem value="fair">Fair</SelectItem>
                    <SelectItem value="poor">Poor</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
            </div>
            <Field>
              <FieldLabel htmlFor="handover_notes">Handover notes</FieldLabel>
              <Textarea id="handover_notes" rows={2} {...register("handover_notes")} />
            </Field>
            <Field>
              <FieldLabel htmlFor="issues_reported">Issues reported</FieldLabel>
              <Textarea id="issues_reported" rows={2} {...register("issues_reported")} />
            </Field>
          </FieldGroup>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={createMutation.isPending}>
              Submit
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
