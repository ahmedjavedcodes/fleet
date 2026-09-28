import { z } from "zod"
import { dateTimeStringSchema, uuidSchema } from "./common"
import { userRoleSchema } from "./enums"

// Mirrors backend/app/schemas/user.py UserResponse. Never includes a password
// hash — there is no UserUpdate schema on the backend either.
export const userSchema = z.object({
  id: uuidSchema,
  organization_id: uuidSchema,
  email: z.string().email(),
  full_name: z.string(),
  phone: z.string().nullable(),
  role: userRoleSchema,
  is_active: z.boolean(),
  last_login_at: dateTimeStringSchema.nullable(),
})
export type User = z.infer<typeof userSchema>
