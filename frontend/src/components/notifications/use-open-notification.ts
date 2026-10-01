"use client"

import { useRouter } from "next/navigation"
import { useMarkNotificationRead } from "@/lib/api/notifications"
import type { Notification } from "@/lib/schemas/notification"

/**
 * What tapping a notification does: it vanishes for the signed-in user (marked read / dismissed per user on the
 * backend; the incident itself is untouched) and, when it is about an incident, opens that incident.
 */
export function useOpenNotification() {
  const router = useRouter()
  const markRead = useMarkNotificationRead()
  return (notification: Notification) => {
    markRead.mutate(notification.id)
    if (notification.incident_id) router.push(`/accountability?incident=${notification.incident_id}`)
  }
}
