import { z } from "zod"
import { dateTimeStringSchema, uuidSchema } from "./common"

// Mirrors backend/app/schemas/notification.py. `warning` and `event` are the
// backend's NotificationType; the page sorts notifications into tabs by it.
export const notificationTypeSchema = z.enum(["warning", "event"])
export type NotificationType = z.infer<typeof notificationTypeSchema>

export const notificationSchema = z.object({
  id: uuidSchema,
  title: z.string(),
  message: z.string(),
  type: notificationTypeSchema,
  is_read: z.boolean(),
  created_at: dateTimeStringSchema,
  // "incident": derived from an unresolved incident, not a stored notification. It has no read state (always read),
  // can't be marked read, and links to the incident.
  source: z.enum(["notification", "incident"]),
  incident_id: uuidSchema.nullable(),
})
export type Notification = z.infer<typeof notificationSchema>
