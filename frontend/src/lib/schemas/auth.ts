import { z } from "zod"
import { driverSchema } from "./driver"
import { organizationSchema } from "./organization"
import { userSchema } from "./user"

// Mirrors backend/app/schemas/auth.py.

export const loginRequestSchema = z.object({
  // Email is unique per-organization, not globally — org_slug disambiguates
  // which organization to check credentials against.
  org_slug: z
    .string()
    .min(1, "Organization is required")
    .regex(/^[a-z0-9-]+$/, "Use lowercase letters, numbers and hyphens only"),
  email: z.string().min(1, "Email is required").email("Enter a valid email"),
  password: z.string().min(1, "Password is required"),
})
export type LoginRequest = z.infer<typeof loginRequestSchema>

export const tokenResponseSchema = z.object({
  access_token: z.string(),
  token_type: z.string(),
  expires_in: z.number().int().positive(),
})
export type TokenResponse = z.infer<typeof tokenResponseSchema>

export const meResponseSchema = z.object({
  user: userSchema,
  organization: organizationSchema,
  driver_profile: driverSchema.nullable(),
})
export type MeResponse = z.infer<typeof meResponseSchema>
