"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useEffect } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { useCreateDriver, useUpdateDriver } from "@/lib/api/drivers"
import { isApiError } from "@/lib/api/errors"
import { driverCreateSchema, type Driver, type DriverCreate } from "@/lib/schemas/driver"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"

export function DriverFormDialog({
  open,
  onOpenChange,
  driver,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  driver?: Driver
}) {
  const isEdit = Boolean(driver)
  const createMutation = useCreateDriver()
  const updateMutation = useUpdateDriver(driver?.id ?? "")
  const mutation = isEdit ? updateMutation : createMutation

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors },
  } = useForm<DriverCreate>({
    resolver: zodResolver(driverCreateSchema),
    defaultValues: { full_name: "", license_number: "", license_expiry: "", phone: "", status: "active" },
  })

  useEffect(() => {
    if (!open) return
    reset(
      driver
        ? {
            full_name: driver.full_name,
            license_number: driver.license_number,
            license_expiry: driver.license_expiry,
            phone: driver.phone,
            status: driver.status,
            user_id: driver.user_id ?? undefined,
          }
        : { full_name: "", license_number: "", license_expiry: "", phone: "", status: "active" }
    )
  }, [open, driver, reset])

  function onSubmit(values: DriverCreate) {
    mutation.mutate(values, {
      onSuccess: () => {
        toast.success(isEdit ? "Driver updated" : "Driver added")
        onOpenChange(false)
      },
      onError: (error) => {
        if (!isApiError(error)) return
        if (error.kind === "validation") {
          for (const [field, message] of Object.entries(error.fieldErrors)) {
            setError(field as keyof DriverCreate, { message })
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
          <DialogTitle>{isEdit ? "Edit driver" : "Add driver"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={(e) => void handleSubmit(onSubmit)(e)} noValidate className="space-y-4">
          <FieldGroup>
            <Field data-invalid={Boolean(errors.full_name)}>
              <FieldLabel htmlFor="full_name">Full name</FieldLabel>
              <Input id="full_name" {...register("full_name")} aria-invalid={Boolean(errors.full_name)} />
              <FieldError errors={[errors.full_name]} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field data-invalid={Boolean(errors.license_number)}>
                <FieldLabel htmlFor="license_number">License number</FieldLabel>
                <Input id="license_number" {...register("license_number")} aria-invalid={Boolean(errors.license_number)} />
                <FieldError errors={[errors.license_number]} />
              </Field>
              <Field data-invalid={Boolean(errors.license_expiry)}>
                <FieldLabel htmlFor="license_expiry">License expiry</FieldLabel>
                <Input id="license_expiry" type="date" {...register("license_expiry")} aria-invalid={Boolean(errors.license_expiry)} />
                <FieldError errors={[errors.license_expiry]} />
              </Field>
            </div>
            <Field data-invalid={Boolean(errors.phone)}>
              <FieldLabel htmlFor="phone">Phone</FieldLabel>
              <Input id="phone" {...register("phone")} aria-invalid={Boolean(errors.phone)} />
              <FieldError errors={[errors.phone]} />
            </Field>
          </FieldGroup>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {isEdit ? "Save changes" : "Add driver"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
