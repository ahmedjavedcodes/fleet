"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useEffect } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { useCreateMaintenanceLog } from "@/lib/api/maintenance"
import { useVehicles } from "@/lib/api/vehicles"
import { isApiError } from "@/lib/api/errors"
import { SERVICE_SCALE_LABELS, SERVICE_TYPE_LABELS } from "@/lib/enum-labels"
import { maintenanceLogCreateSchema, type MaintenanceLogCreate } from "@/lib/schemas/maintenance"
import type { ServiceScale, ServiceType } from "@/lib/schemas/enums"
import { DriverSelect } from "@/components/fleet/driver-select"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"

const SERVICE_TYPES = Object.keys(SERVICE_TYPE_LABELS) as ServiceType[]
const SERVICE_SCALES = Object.keys(SERVICE_SCALE_LABELS) as ServiceScale[]

export function MaintenanceFormDialog({
  open,
  onOpenChange,
  defaultVehicleId,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  defaultVehicleId?: string
}) {
  const vehiclesQuery = useVehicles()
  const createMutation = useCreateMaintenanceLog()
  const {
    register,
    handleSubmit,
    reset,
    setError,
    setValue,
    watch,
    formState: { errors },
  } = useForm<MaintenanceLogCreate>({
    resolver: zodResolver(maintenanceLogCreateSchema),
    defaultValues: { vehicle_id: defaultVehicleId ?? "", date: new Date().toISOString().slice(0, 10), odometer_at_service: 0, service_types: ["oil_change"], service_scale: "minor" },
  })

  useEffect(() => {
    if (open) reset({ vehicle_id: defaultVehicleId ?? "", date: new Date().toISOString().slice(0, 10), odometer_at_service: 0, service_types: ["oil_change"], service_scale: "minor" })
  }, [open, defaultVehicleId, reset])

  function onSubmit(values: MaintenanceLogCreate) {
    createMutation.mutate(values, {
      onSuccess: () => {
        toast.success("Service logged")
        onOpenChange(false)
      },
      onError: (error) => {
        if (!isApiError(error)) return
        if (error.kind === "validation") {
          for (const [field, message] of Object.entries(error.fieldErrors)) {
            setError(field as keyof MaintenanceLogCreate, { message })
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
          <DialogTitle>Log service</DialogTitle>
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
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field data-invalid={Boolean(errors.date)}>
                <FieldLabel htmlFor="date">Date</FieldLabel>
                <Input id="date" type="date" {...register("date")} />
                <FieldError errors={[errors.date]} />
              </Field>
              <Field data-invalid={Boolean(errors.odometer_at_service)}>
                <FieldLabel htmlFor="odometer_at_service">Odometer (km)</FieldLabel>
                <Input id="odometer_at_service" type="number" {...register("odometer_at_service", { valueAsNumber: true })} />
                <FieldError errors={[errors.odometer_at_service]} />
              </Field>
            </div>
            <Field data-invalid={Boolean(errors.service_types)}>
              <FieldLabel>Services performed</FieldLabel>
              <ToggleGroup
                type="multiple"
                variant="outline"
                size="sm"
                className="w-full flex-wrap justify-start"
                aria-label="Services performed"
                value={watch("service_types") ?? []}
                onValueChange={(v) => setValue("service_types", v as ServiceType[], { shouldValidate: true })}
              >
                {SERVICE_TYPES.map((t) => (
                  <ToggleGroupItem key={t} value={t}>
                    {SERVICE_TYPE_LABELS[t]}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
              <FieldError errors={[errors.service_types as { message?: string } | undefined]} />
            </Field>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field>
                <FieldLabel htmlFor="service_scale">Scale</FieldLabel>
                <Select value={watch("service_scale")} onValueChange={(v) => setValue("service_scale", v as ServiceScale)}>
                  <SelectTrigger id="service_scale" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SERVICE_SCALES.map((s) => (
                      <SelectItem key={s} value={s}>
                        {SERVICE_SCALE_LABELS[s]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field>
                <FieldLabel htmlFor="driver_id">Brought in by</FieldLabel>
                <DriverSelect id="driver_id" value={watch("driver_id")} onChange={(v) => setValue("driver_id", v)} />
              </Field>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field data-invalid={Boolean(errors.cost)}>
                <FieldLabel htmlFor="cost">Cost (PKR)</FieldLabel>
                <Input id="cost" type="number" step="0.01" {...register("cost", { valueAsNumber: true, setValueAs: (v) => (v === "" || Number.isNaN(v) ? undefined : v) })} />
                <FieldError errors={[errors.cost]} />
              </Field>
              <Field>
                <FieldLabel htmlFor="mechanic_name">Mechanic</FieldLabel>
                <Input id="mechanic_name" {...register("mechanic_name")} />
              </Field>
            </div>
            <Field>
              <FieldLabel htmlFor="description">Description</FieldLabel>
              <Textarea id="description" rows={2} {...register("description")} />
            </Field>
          </FieldGroup>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={createMutation.isPending}>
              Log service
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
