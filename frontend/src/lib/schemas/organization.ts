import { z } from "zod"
import { dateTimeStringSchema, uuidSchema } from "./common"
import { subscriptionTierSchema } from "./enums"

// Mirrors backend/app/schemas/organization.py OrganizationResponse.
export const organizationSchema = z.object({
  id: uuidSchema,
  name: z.string(),
  slug: z.string(),
  subscription_tier: subscriptionTierSchema,
  created_at: dateTimeStringSchema,
})
export type Organization = z.infer<typeof organizationSchema>
