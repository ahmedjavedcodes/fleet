"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Truck } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { ApiError } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import { loginSchema, type LoginFormValues } from "@/lib/schemas/auth";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";

export default function LoginPage() {
  const { login } = useAuth();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({ resolver: zodResolver(loginSchema) });

  const onSubmit = async (values: LoginFormValues) => {
    setFormError(null);
    try {
      await login(values);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.kind === "validation") {
          for (const [field, message] of Object.entries(err.fieldErrors)) {
            setError(field as keyof LoginFormValues, { message });
          }
        } else if (err.kind === "unauthorized" || err.kind === "not_found") {
          setFormError("Invalid organization, email, or password.");
        } else {
          setFormError(err.message);
        }
      } else {
        setFormError("Something went wrong. Please try again.");
      }
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center gap-2">
          <Truck className="h-6 w-6" />
          <h1 className="text-xl font-semibold">Fleet Copilot</h1>
        </div>

        {formError && (
          <div className="mb-4">
            <ErrorBanner message={formError} />
          </div>
        )}

        <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
          <Field label="Organization slug" error={errors.org_slug?.message}>
            <input
              {...register("org_slug")}
              placeholder="acme-logistics"
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-900"
            />
          </Field>

          <Field label="Email" error={errors.email?.message}>
            <input
              {...register("email")}
              type="email"
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-900"
            />
          </Field>

          <Field label="Password" error={errors.password?.message}>
            <input
              {...register("password")}
              type="password"
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-900"
            />
          </Field>

          <button
            type="submit"
            disabled={isSubmitting}
            className="flex items-center justify-center gap-2 rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60 dark:bg-white dark:text-neutral-900"
          >
            {isSubmitting && <Spinner className="h-4 w-4" />}
            Sign in
          </button>
        </form>
      </div>
    </main>
  );
}

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-sm font-medium text-neutral-700 dark:text-neutral-300">{label}</span>
      {children}
      {error && <span className="text-xs text-red-600 dark:text-red-400">{error}</span>}
    </label>
  );
}
