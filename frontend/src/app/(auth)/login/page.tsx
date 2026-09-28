"use client"

import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Loader2, Truck } from "lucide-react"
import { useRouter, useSearchParams } from "next/navigation"
import { useForm } from "react-hook-form"
import { login } from "@/lib/api/auth"
import { isApiError } from "@/lib/api/errors"
import { safeNextPath } from "@/lib/auth/safe-next-path"
import { meKeys } from "@/lib/query/keys"
import { loginRequestSchema, type LoginRequest } from "@/lib/schemas/auth"
import { APP_NAME } from "@/lib/brand"
import { Button } from "@/components/ui/button"
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"

const UNAUTHORIZED_MESSAGE = "Invalid organization, email or password."

export default function LoginPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()

  const {
    register,
    handleSubmit,
    setError,
    clearErrors,
    formState: { errors },
  } = useForm<LoginRequest>({
    resolver: zodResolver(loginRequestSchema),
    mode: "onBlur",
    defaultValues: { org_slug: "", email: "", password: "" },
  })

  const loginMutation = useMutation({
    mutationFn: login,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: meKeys.all })
      const next = safeNextPath(searchParams.get("next"))
      router.replace(next ?? "/dashboard")
    },
    onError: (error) => {
      if (!isApiError(error)) {
        setError("root", { message: "Couldn't reach the server. Check your connection and try again." })
        return
      }
      if (error.kind === "unauthorized") {
        setError("root", { message: UNAUTHORIZED_MESSAGE })
        return
      }
      if (error.kind === "validation") {
        const fields = Object.entries(error.fieldErrors)
        if (fields.length === 0) {
          setError("root", { message: error.message })
          return
        }
        for (const [field, message] of fields) {
          if (field === "org_slug" || field === "email" || field === "password") {
            setError(field, { message })
          }
        }
        return
      }
      setError("root", { message: "message" in error ? error.message : "Something went wrong. Please try again." })
    },
  })

  function onSubmit(values: LoginRequest) {
    clearErrors("root")
    loginMutation.mutate(values)
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-2 text-center">
          <div className="flex size-12 items-center justify-center rounded-xl bg-primary-soft">
            <Truck className="size-6 text-primary" aria-hidden />
          </div>
          <span className="text-h2 font-semibold">{APP_NAME}</span>
        </div>

        <form
          onSubmit={(event) => void handleSubmit(onSubmit)(event)}
          noValidate
          className="rounded-xl border border-border bg-card p-6 shadow-card"
        >
          <FieldGroup>
            <Field data-invalid={Boolean(errors.org_slug)}>
              <FieldLabel htmlFor="org_slug">Organization</FieldLabel>
              <Input
                id="org_slug"
                autoComplete="organization"
                placeholder="your-company"
                aria-invalid={Boolean(errors.org_slug)}
                {...register("org_slug")}
              />
              <FieldError errors={[errors.org_slug]} />
            </Field>

            <Field data-invalid={Boolean(errors.email)}>
              <FieldLabel htmlFor="email">Email</FieldLabel>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                placeholder="you@example.com"
                aria-invalid={Boolean(errors.email)}
                {...register("email")}
              />
              <FieldError errors={[errors.email]} />
            </Field>

            <Field data-invalid={Boolean(errors.password)}>
              <FieldLabel htmlFor="password">Password</FieldLabel>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                aria-invalid={Boolean(errors.password)}
                {...register("password")}
              />
              <FieldError errors={[errors.password]} />
            </Field>

            {errors.root ? (
              <p role="alert" className="text-sm font-normal text-destructive">
                {errors.root.message}
              </p>
            ) : null}

            <Button type="submit" disabled={loginMutation.isPending} className="w-full">
              {loginMutation.isPending ? <Loader2 className="animate-spin" aria-hidden /> : null}
              Sign in
            </Button>
          </FieldGroup>
        </form>
      </div>
    </main>
  )
}
