"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useEffect } from "react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { useCreateSupplier, useUpdateSupplier } from "@/lib/api/suppliers"
import { isApiError } from "@/lib/api/errors"
import { supplierCreateSchema, type Supplier, type SupplierCreate } from "@/lib/schemas/supplier"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"

export function SupplierFormDialog({
  open,
  onOpenChange,
  supplier,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  supplier?: Supplier
}) {
  const isEdit = Boolean(supplier)
  const createMutation = useCreateSupplier()
  const updateMutation = useUpdateSupplier(supplier?.id ?? "")
  const mutation = isEdit ? updateMutation : createMutation

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors },
  } = useForm<SupplierCreate>({
    resolver: zodResolver(supplierCreateSchema),
    defaultValues: { name: "" },
  })

  useEffect(() => {
    if (!open) return
    reset(
      supplier
        ? {
            name: supplier.name,
            contact_email: supplier.contact_email ?? undefined,
            phone: supplier.phone ?? undefined,
            avg_lead_time_days: supplier.avg_lead_time_days ?? undefined,
          }
        : { name: "" }
    )
  }, [open, supplier, reset])

  function onSubmit(values: SupplierCreate) {
    mutation.mutate(values, {
      onSuccess: () => {
        toast.success(isEdit ? "Supplier updated" : "Supplier added")
        onOpenChange(false)
      },
      onError: (error) => {
        if (!isApiError(error)) return
        if (error.kind === "validation") {
          for (const [field, message] of Object.entries(error.fieldErrors)) {
            setError(field as keyof SupplierCreate, { message })
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
          <DialogTitle>{isEdit ? "Edit supplier" : "Add supplier"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={(e) => void handleSubmit(onSubmit)(e)} noValidate className="space-y-4">
          <FieldGroup>
            <Field data-invalid={Boolean(errors.name)}>
              <FieldLabel htmlFor="name">Name</FieldLabel>
              <Input id="name" {...register("name")} aria-invalid={Boolean(errors.name)} />
              <FieldError errors={[errors.name]} />
            </Field>
            <Field data-invalid={Boolean(errors.contact_email)}>
              <FieldLabel htmlFor="contact_email">Contact email</FieldLabel>
              <Input id="contact_email" type="email" {...register("contact_email")} aria-invalid={Boolean(errors.contact_email)} />
              <FieldError errors={[errors.contact_email]} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field data-invalid={Boolean(errors.phone)}>
                <FieldLabel htmlFor="phone">Phone</FieldLabel>
                <Input id="phone" {...register("phone")} aria-invalid={Boolean(errors.phone)} />
                <FieldError errors={[errors.phone]} />
              </Field>
              <Field data-invalid={Boolean(errors.avg_lead_time_days)}>
                <FieldLabel htmlFor="avg_lead_time_days">Avg lead time (days)</FieldLabel>
                <Input id="avg_lead_time_days" type="number" {...register("avg_lead_time_days", { valueAsNumber: true })} />
                <FieldError errors={[errors.avg_lead_time_days]} />
              </Field>
            </div>
          </FieldGroup>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {isEdit ? "Save changes" : "Add supplier"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
