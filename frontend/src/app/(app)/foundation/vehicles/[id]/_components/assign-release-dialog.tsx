"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { useAssignVehicle, useReleaseVehicle } from "@/lib/api/vehicles"
import { useDrivers } from "@/lib/api/drivers"
import { isApiError } from "@/lib/api/errors"
import { vehicleAssignRequestSchema, vehicleReleaseRequestSchema, type VehicleAssignRequest, type VehicleReleaseRequest } from "@/lib/schemas/assignment"
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
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

function toDateTimeLocal(iso: string): string {
  const d = new Date(iso)
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
}

export function AssignDriverDialog({
  open,
  onOpenChange,
  vehicleId,
  currentOdometer,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  vehicleId: string
  currentOdometer: number
}) {
  const driversQuery = useDrivers()
  const assignMutation = useAssignVehicle(vehicleId)
  const {
    register,
    handleSubmit,
    setError,
    setValue,
    watch,
    formState: { errors },
  } = useForm<VehicleAssignRequest>({
    resolver: zodResolver(vehicleAssignRequestSchema),
    defaultValues: {
      driver_id: "",
      assigned_at: toDateTimeLocal(new Date().toISOString()),
      start_odometer: currentOdometer,
      take_condition: "good",
    },
  })

  function onSubmit(values: VehicleAssignRequest) {
    assignMutation.mutate(
      { ...values, assigned_at: new Date(values.assigned_at).toISOString() },
      {
        onSuccess: () => {
          toast.success("Driver assigned")
          onOpenChange(false)
        },
        onError: (error) => {
          if (!isApiError(error)) return
          if (error.kind === "conflict") {
            setError("driver_id", { message: "This vehicle already has a driver. Refresh and try again." })
            return
          }
          if (error.kind === "bad_request" || error.kind === "validation") {
            toast.error(error.message)
            return
          }
        },
      }
    )
  }

  const activeDrivers = (driversQuery.data ?? []).filter((d) => d.status === "active")

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Assign driver</DialogTitle>
        </DialogHeader>
        <form onSubmit={(e) => void handleSubmit(onSubmit)(e)} noValidate className="space-y-4">
          <FieldGroup>
            <Field data-invalid={Boolean(errors.driver_id)}>
              <FieldLabel htmlFor="driver_id">Driver</FieldLabel>
              <Select value={watch("driver_id")} onValueChange={(v) => setValue("driver_id", v)}>
                <SelectTrigger id="driver_id" className="w-full">
                  <SelectValue placeholder="Select a driver" />
                </SelectTrigger>
                <SelectContent>
                  {activeDrivers.map((d) => (
                    <SelectItem key={d.id} value={d.id}>
                      {d.full_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FieldError errors={[errors.driver_id]} />
            </Field>
            <Field data-invalid={Boolean(errors.assigned_at)}>
              <FieldLabel htmlFor="assigned_at">Assigned at</FieldLabel>
              <Input id="assigned_at" type="datetime-local" {...register("assigned_at")} />
              <FieldError errors={[errors.assigned_at]} />
            </Field>
            <Field data-invalid={Boolean(errors.start_odometer)}>
              <FieldLabel htmlFor="start_odometer">Start odometer (km)</FieldLabel>
              <Input id="start_odometer" type="number" {...register("start_odometer", { valueAsNumber: true })} />
              <FieldError errors={[errors.start_odometer]} />
            </Field>
            <Field>
              <FieldLabel htmlFor="take_condition">Condition on handover</FieldLabel>
              <Select value={watch("take_condition")} onValueChange={(v) => setValue("take_condition", v as VehicleAssignRequest["take_condition"])}>
                <SelectTrigger id="take_condition" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="good">Good</SelectItem>
                  <SelectItem value="fair">Fair</SelectItem>
                  <SelectItem value="poor">Poor</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          </FieldGroup>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={assignMutation.isPending}>
              Assign
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// Release is a destructive-class custody action (CLAUDE.md §6) — confirm
// first, then the actual form.
export function ReleaseDriverFlow({
  open,
  onOpenChange,
  vehicleId,
  currentOdometer,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  vehicleId: string
  currentOdometer: number
}) {
  const [confirmed, setConfirmed] = useState(false)
  const releaseMutation = useReleaseVehicle(vehicleId)
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors },
  } = useForm<VehicleReleaseRequest>({
    resolver: zodResolver(vehicleReleaseRequestSchema),
    defaultValues: {
      released_at: toDateTimeLocal(new Date().toISOString()),
      end_odometer: currentOdometer,
      leave_condition: "good",
    },
  })

  function close() {
    setConfirmed(false)
    onOpenChange(false)
  }

  function onSubmit(values: VehicleReleaseRequest) {
    releaseMutation.mutate(
      { ...values, released_at: new Date(values.released_at).toISOString() },
      {
        onSuccess: () => {
          toast.success("Driver released")
          close()
        },
        onError: (error) => {
          if (isApiError(error) && "message" in error) toast.error(error.message)
        },
      }
    )
  }

  if (!confirmed) {
    return (
      <AlertDialog open={open} onOpenChange={(o) => !o && close()}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Release this driver?</AlertDialogTitle>
            <AlertDialogDescription>You&apos;ll record the end odometer and vehicle condition next.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => setConfirmed(true)}>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    )
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && close()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Release driver</DialogTitle>
        </DialogHeader>
        <form onSubmit={(e) => void handleSubmit(onSubmit)(e)} noValidate className="space-y-4">
          <FieldGroup>
            <Field data-invalid={Boolean(errors.released_at)}>
              <FieldLabel htmlFor="released_at">Released at</FieldLabel>
              <Input id="released_at" type="datetime-local" {...register("released_at")} />
              <FieldError errors={[errors.released_at]} />
            </Field>
            <Field data-invalid={Boolean(errors.end_odometer)}>
              <FieldLabel htmlFor="end_odometer">End odometer (km)</FieldLabel>
              <Input id="end_odometer" type="number" {...register("end_odometer", { valueAsNumber: true })} />
              <FieldError errors={[errors.end_odometer]} />
            </Field>
            <Field>
              <FieldLabel htmlFor="leave_condition">Condition on return</FieldLabel>
              <Select value={watch("leave_condition")} onValueChange={(v) => setValue("leave_condition", v as VehicleReleaseRequest["leave_condition"])}>
                <SelectTrigger id="leave_condition" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="good">Good</SelectItem>
                  <SelectItem value="fair">Fair</SelectItem>
                  <SelectItem value="poor">Poor</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          </FieldGroup>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              Cancel
            </Button>
            <Button type="submit" variant="destructive" disabled={releaseMutation.isPending}>
              Release
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
