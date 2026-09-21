// Mirrors backend/app/schemas/auth.py::LoginRequest / RegisterRequest.
// Keep in sync with src/lib/types/auth.ts and the backend schema together.
import { z } from "zod";

export const loginSchema = z.object({
  org_slug: z
    .string()
    .min(2, "Organization slug is required")
    .regex(/^[a-z0-9-]+$/, "Lowercase letters, numbers, and hyphens only"),
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});

export type LoginFormValues = z.infer<typeof loginSchema>;

export const registerSchema = z.object({
  organization_name: z.string().min(2, "Organization name is required"),
  organization_slug: z
    .string()
    .min(2, "Slug must be at least 2 characters")
    .max(100)
    .regex(/^[a-z0-9-]+$/, "Lowercase letters, numbers, and hyphens only"),
  admin_email: z.string().email("Enter a valid email address"),
  admin_password: z.string().min(8, "Password must be at least 8 characters"),
  admin_full_name: z.string().min(1, "Full name is required"),
});

export type RegisterFormValues = z.infer<typeof registerSchema>;
