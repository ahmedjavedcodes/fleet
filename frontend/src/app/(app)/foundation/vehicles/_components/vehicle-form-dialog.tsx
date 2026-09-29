"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useEffect } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { useCreateVehicle, useUpdateVehicle } from "@/lib/api/vehicles"
import { isApiError } from "@/lib/api/errors"
import { VEHICLE_OWNERSHIP_LABELS } from "@/lib/enum-labels"
import { emptyToUndefined } from "@/lib/form-utils"
import type { VehicleOwnershipType } from "@/lib/schemas/enums"
import { vehicleCreateSchema, type Vehicle, type VehicleCreate } from "@/lib/schemas/vehicle"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

const FUEL_TYPES = ["diesel", "petrol", "hybrid", "electric"] as const
const STATUSES = ["active", "maintenance", "retired"] as const
const OWNERSHIP_TYPES = Object.keys(VEHICLE_OWNERSHIP_LABELS) as VehicleOwnershipType[]

// One dialog for both create (no `vehicle`) and edit (`vehicle` set) — same
// fields either way, just a different mutation and submit label.
export function VehicleFormDialog({
  open,
  onOpenChange,
  vehicle,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  vehicle?: Vehicle
}) {
  const isEdit = Boolean(vehicle)
  const createMutation = useCreateVehicle()
  const updateMutation = useUpdateVehicle(vehicle?.id ?? "")
  const mutation = isEdit ? updateMutation : createMutation

  const {
    register,
    handleSubmit,
    reset,
    setError,
    setValue,
    watch,
    formState: { errors },
  } = useForm<VehicleCreate>({
    resolver: zodResolver(vehicleCreateSchema),
    defaultValues: {
      plate_number: "",
      make: "",
      model: "",
      year: new Date().getFullYear(),
      vin: "",
      fuel_type: "petrol",
      status: "active",
      current_odometer: 0,
      ownership_type: "owner",
    },
  })

  useEffect(() => {
    if (!open) return
    reset(
      vehicle
        ? {
            plate_number: vehicle.plate_number,
            make: vehicle.make,
            model: vehicle.model,
            year: vehicle.year,
            vin: vehicle.vin,
            fuel_type: vehicle.fuel_type,
            status: vehicle.status,
            current_odometer: vehicle.current_odometer,
            ownership_type: vehicle.ownership_type,
            engine_number: vehicle.engine_number ?? undefined,
            chassis_number: vehicle.chassis_number ?? undefined,
            service_interval_km: vehicle.service_interval_km ?? undefined,
            service_interval_months: vehicle.service_interval_months ?? undefined,
          }
        : {
            plate_number: "",
            make: "",
            model: "",
            year: new Date().getFullYear(),
            vin: "",
            fuel_type: "petrol",
            status: "active",
            current_odometer: 0,
            ownership_type: "owner",
          }
    )
  }, [open, vehicle, reset])

  function onSubmit(values: VehicleCreate) {
    mutation.mutate(values, {
      onSuccess: () => {
        toast.success(isEdit ? "Vehicle updated" : "Vehicle added")
        onOpenChange(false)
      },
      onError: (error) => {
        if (!isApiError(error)) return
        if (error.kind === "validation") {
          for (const [field, message] of Object.entries(error.fieldErrors)) {
            setError(field as keyof VehicleCreate, { message })
          }
          return
        }
        if (error.kind === "conflict") {
          setError("plate_number", { message: "A vehicle with this plate number or VIN already exists." })
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
          <DialogTitle>{isEdit ? "Edit vehicle" : "Add vehicle"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={(e) => void handleSubmit(onSubmit)(e)} noValidate className="space-y-4">
          <FieldGroup>
            <div className="grid grid-cols-2 gap-3">
              <Field data-invalid={Boolean(errors.plate_number)}>
                <FieldLabel htmlFor="plate_number">Plate number</FieldLabel>
                <Input id="plate_number" {...register("plate_number")} aria-invalid={Boolean(errors.plate_number)} />
                <FieldError errors={[errors.plate_number]} />
              </Field>
              <Field data-invalid={Boolean(errors.vin)}>
                <FieldLabel htmlFor="vin">VIN</FieldLabel>
                <Input id="vin" {...register("vin")} aria-invalid={Boolean(errors.vin)} />
                <FieldError errors={[errors.vin]} />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field data-invalid={Boolean(errors.make)}>
                <FieldLabel htmlFor="make">Make</FieldLabel>
                <Input id="make" {...register("make")} aria-invalid={Boolean(errors.make)} />
                <FieldError errors={[errors.make]} />
              </Field>
              <Field data-invalid={Boolean(errors.model)}>
                <FieldLabel htmlFor="model">Model</FieldLabel>
                <Input id="model" {...register("model")} aria-invalid={Boolean(errors.model)} />
                <FieldError errors={[errors.model]} />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field data-invalid={Boolean(errors.year)}>
                <FieldLabel htmlFor="year">Year</FieldLabel>
                <Input id="year" type="number" {...register("year", { valueAsNumber: true })} aria-invalid={Boolean(errors.year)} />
                <FieldError errors={[errors.year]} />
              </Field>
              <Field data-invalid={Boolean(errors.current_odometer)}>
                <FieldLabel htmlFor="current_odometer">Odometer (km)</FieldLabel>
                <Input
                  id="current_odometer"
                  type="number"
                  {...register("current_odometer", { valueAsNumber: true })}
                  aria-invalid={Boolean(errors.current_odometer)}
                />
                <FieldError errors={[errors.current_odometer]} />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field>
                <FieldLabel htmlFor="fuel_type">Fuel type</FieldLabel>
                <Select value={watch("fuel_type")} onValueChange={(v) => setValue("fuel_type", v as VehicleCreate["fuel_type"])}>
                  <SelectTrigger id="fuel_type" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {FUEL_TYPES.map((t) => (
                      <SelectItem key={t} value={t}>
                        {t[0]!.toUpperCase() + t.slice(1)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field>
                <FieldLabel htmlFor="status">Status</FieldLabel>
                <Select value={watch("status")} onValueChange={(v) => setValue("status", v as VehicleCreate["status"])}>
                  <SelectTrigger id="status" className="w-full">
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
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field>
                <FieldLabel htmlFor="engine_number">Engine number</FieldLabel>
                <Input id="engine_number" {...register("engine_number", { setValueAs: emptyToUndefined })} />
              </Field>
              <Field>
                <FieldLabel htmlFor="chassis_number">Chassis number</FieldLabel>
                <Input id="chassis_number" {...register("chassis_number", { setValueAs: emptyToUndefined })} />
              </Field>
            </div>
            <Field>
              <FieldLabel htmlFor="ownership_type">Ownership</FieldLabel>
              <Select
                value={watch("ownership_type")}
                onValueChange={(v) => setValue("ownership_type", v as VehicleOwnershipType)}
              >
                <SelectTrigger id="ownership_type" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {OWNERSHIP_TYPES.map((t) => (
                    <SelectItem key={t} value={t}>
                      {VEHICLE_OWNERSHIP_LABELS[t]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field>
                <FieldLabel htmlFor="service_interval_km">Service every (km)</FieldLabel>
                <Input
                  id="service_interval_km"
                  type="number"
                  {...register("service_interval_km", { valueAsNumber: true, setValueAs: (v) => (v === "" || Number.isNaN(v) ? undefined : v) })}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="service_interval_months">Service every (months)</FieldLabel>
                <Input
                  id="service_interval_months"
                  type="number"
                  {...register("service_interval_months", { valueAsNumber: true, setValueAs: (v) => (v === "" || Number.isNaN(v) ? undefined : v) })}
                />
              </Field>
            </div>
          </FieldGroup>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {isEdit ? "Save changes" : "Add vehicle"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
