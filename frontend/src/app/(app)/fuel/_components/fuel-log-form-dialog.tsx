"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useEffect } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { useCreateFuelLog } from "@/lib/api/fuel"
import { useVehicles } from "@/lib/api/vehicles"
import { isApiError } from "@/lib/api/errors"
import { useCurrentUser } from "@/lib/auth/use-current-user"
import { emptyToUndefined } from "@/lib/form-utils"
import { DriverSelect } from "@/components/fleet/driver-select"
import { fuelLogCreateSchema, type FuelLogCreate } from "@/lib/schemas/fuel"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

export function FuelLogFormDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const vehiclesQuery = useVehicles()
  // A driver-role user always logs for themself (the backend forces it), so only
  // admins get to pick a driver.
  const { role } = useCurrentUser()
  const canPickDriver = role !== null && role !== "driver"
  const createMutation = useCreateFuelLog()
  const {
    register,
    handleSubmit,
    reset,
    setError,
    setValue,
    watch,
    formState: { errors },
  } = useForm<FuelLogCreate>({
    resolver: zodResolver(fuelLogCreateSchema),
    defaultValues: { vehicle_id: "", date: new Date().toISOString().slice(0, 10), odometer_reading: 0, liters_filled: 0, price_per_liter: 0, total_cost: 0 },
  })

  useEffect(() => {
    if (open) reset({ vehicle_id: "", date: new Date().toISOString().slice(0, 10), odometer_reading: 0, liters_filled: 0, price_per_liter: 0, total_cost: 0 })
  }, [open, reset])

  function onSubmit(values: FuelLogCreate) {
    createMutation.mutate(values, {
      onSuccess: () => {
        toast.success("Fuel log added")
        onOpenChange(false)
      },
      onError: (error) => {
        if (!isApiError(error)) return
        if (error.kind === "validation") {
          if (Object.keys(error.fieldErrors).length === 0) {
            setError("root", { message: error.message })
            return
          }
          for (const [field, message] of Object.entries(error.fieldErrors)) {
            setError(field as keyof FuelLogCreate, { message })
          }
          return
        }
        if (error.kind === "bad_request") {
          setError("odometer_reading", { message: error.message })
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
          <DialogTitle>Log fuel</DialogTitle>
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
            {canPickDriver ? (
              <Field>
                <FieldLabel htmlFor="driver_id">Driver</FieldLabel>
                <DriverSelect id="driver_id" value={watch("driver_id")} onChange={(v) => setValue("driver_id", v)} />
              </Field>
            ) : null}
            <div className="grid grid-cols-2 gap-3">
              <Field data-invalid={Boolean(errors.date)}>
                <FieldLabel htmlFor="date">Date</FieldLabel>
                <Input id="date" type="date" {...register("date")} />
                <FieldError errors={[errors.date]} />
              </Field>
              <Field data-invalid={Boolean(errors.odometer_reading)}>
                <FieldLabel htmlFor="odometer_reading">Odometer (km)</FieldLabel>
                <Input id="odometer_reading" type="number" {...register("odometer_reading", { valueAsNumber: true })} />
                <FieldError errors={[errors.odometer_reading]} />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field data-invalid={Boolean(errors.liters_filled)}>
                <FieldLabel htmlFor="liters_filled">Liters</FieldLabel>
                <Input id="liters_filled" type="number" step="0.01" {...register("liters_filled", { valueAsNumber: true })} />
                <FieldError errors={[errors.liters_filled]} />
              </Field>
              <Field data-invalid={Boolean(errors.price_per_liter)}>
                <FieldLabel htmlFor="price_per_liter">Price/liter</FieldLabel>
                <Input id="price_per_liter" type="number" step="0.01" {...register("price_per_liter", { valueAsNumber: true })} />
                <FieldError errors={[errors.price_per_liter]} />
              </Field>
            </div>
            <Field data-invalid={Boolean(errors.total_cost)}>
              <FieldLabel htmlFor="total_cost">Total cost (PKR)</FieldLabel>
              <Input id="total_cost" type="number" step="0.01" {...register("total_cost", { valueAsNumber: true })} />
              <FieldError errors={[errors.total_cost]} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field>
                <FieldLabel htmlFor="slip_id">Slip ID</FieldLabel>
                <Input id="slip_id" {...register("slip_id", { setValueAs: emptyToUndefined })} />
              </Field>
              <Field>
                <FieldLabel htmlFor="po_number">PO number</FieldLabel>
                <Input id="po_number" {...register("po_number", { setValueAs: emptyToUndefined })} />
              </Field>
            </div>
            <Field>
              <FieldLabel htmlFor="fuel_station_name">Fuel station</FieldLabel>
              <Input id="fuel_station_name" {...register("fuel_station_name", { setValueAs: emptyToUndefined })} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field>
                <FieldLabel htmlFor="payment_method">Payment method</FieldLabel>
                <Input
                  id="payment_method"
                  placeholder="cash, card, fuel card"
                  {...register("payment_method", { setValueAs: emptyToUndefined })}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="card_used">Card used</FieldLabel>
                <Input
                  id="card_used"
                  placeholder="Last 4 digits or name"
                  {...register("card_used", { setValueAs: emptyToUndefined })}
                />
              </Field>
            </div>
            {errors.root ? <p className="text-sm text-destructive">{errors.root.message}</p> : null}
          </FieldGroup>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={createMutation.isPending}>
              Log fuel
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
