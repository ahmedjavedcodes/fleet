"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useEffect } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { useCreateTrip } from "@/lib/api/trips"
import { useVehicles } from "@/lib/api/vehicles"
import { useDrivers } from "@/lib/api/drivers"
import { isApiError } from "@/lib/api/errors"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import { tripLogCreateSchema, type TripLogCreate } from "@/lib/schemas/trip"
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

export function TripFormDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { role, driverProfile } = useCurrentUser()
  const vehiclesQuery = useVehicles()
  const driversQuery = useDrivers()
  const createMutation = useCreateTrip()

  const {
    register,
    handleSubmit,
    reset,
    setError,
    setValue,
    watch,
    formState: { errors },
  } = useForm<TripLogCreate>({
    resolver: zodResolver(tripLogCreateSchema),
    defaultValues: {
      driver_id: driverProfile?.id ?? "",
      vehicle_id: "",
      start_time: toDateTimeLocal(new Date().toISOString()),
      end_time: toDateTimeLocal(new Date().toISOString()),
      start_odometer: 0,
      end_odometer: 0,
    },
  })

  useEffect(() => {
    if (open) {
      reset({
        driver_id: driverProfile?.id ?? "",
        vehicle_id: "",
        start_time: toDateTimeLocal(new Date().toISOString()),
        end_time: toDateTimeLocal(new Date().toISOString()),
        start_odometer: 0,
        end_odometer: 0,
      })
    }
  }, [open, driverProfile, reset])

  function onSubmit(values: TripLogCreate) {
    createMutation.mutate(
      { ...values, start_time: new Date(values.start_time).toISOString(), end_time: new Date(values.end_time).toISOString() },
      {
        onSuccess: () => {
          toast.success("Trip logged")
          onOpenChange(false)
        },
        onError: (error) => {
          if (!isApiError(error)) return
          if (error.kind === "validation") {
            for (const [field, message] of Object.entries(error.fieldErrors)) {
              setError(field as keyof TripLogCreate, { message })
            }
            return
          }
          toast.error("message" in error ? error.message : "Something went wrong. Please try again.")
        },
      }
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Log trip</DialogTitle>
        </DialogHeader>
        <form onSubmit={(e) => void handleSubmit(onSubmit)(e)} noValidate className="space-y-4">
          <FieldGroup>
            {role === "admin" ? (
              <Field data-invalid={Boolean(errors.driver_id)}>
                <FieldLabel htmlFor="driver_id">Driver</FieldLabel>
                <Select value={watch("driver_id")} onValueChange={(v) => setValue("driver_id", v)}>
                  <SelectTrigger id="driver_id" className="w-full">
                    <SelectValue placeholder="Select a driver" />
                  </SelectTrigger>
                  <SelectContent>
                    {(driversQuery.data ?? []).map((d) => (
                      <SelectItem key={d.id} value={d.id}>
                        {d.full_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <FieldError errors={[errors.driver_id]} />
              </Field>
            ) : null}
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
              <Field data-invalid={Boolean(errors.start_time)}>
                <FieldLabel htmlFor="start_time">Start time</FieldLabel>
                <Input id="start_time" type="datetime-local" {...register("start_time")} />
                <FieldError errors={[errors.start_time]} />
              </Field>
              <Field data-invalid={Boolean(errors.end_time)}>
                <FieldLabel htmlFor="end_time">End time</FieldLabel>
                <Input id="end_time" type="datetime-local" {...register("end_time")} />
                <FieldError errors={[errors.end_time]} />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field data-invalid={Boolean(errors.start_odometer)}>
                <FieldLabel htmlFor="start_odometer">Start odometer</FieldLabel>
                <Input id="start_odometer" type="number" {...register("start_odometer", { valueAsNumber: true })} />
                <FieldError errors={[errors.start_odometer]} />
              </Field>
              <Field data-invalid={Boolean(errors.end_odometer)}>
                <FieldLabel htmlFor="end_odometer">End odometer</FieldLabel>
                <Input id="end_odometer" type="number" {...register("end_odometer", { valueAsNumber: true })} />
                <FieldError errors={[errors.end_odometer]} />
              </Field>
            </div>
          </FieldGroup>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={createMutation.isPending}>
              Log trip
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
