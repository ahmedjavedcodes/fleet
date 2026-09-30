import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { z } from "zod"
import { notificationKeys } from "@/lib/query/keys"
import { notificationSchema, type Notification } from "@/lib/schemas/notification"
import { apiRequest } from "./client"

// The signed-in user's own notifications. Every role has them; the backend
// never returns anyone else's.

export function listNotifications(): Promise<Notification[]> {
  return apiRequest("/notifications", { schema: z.array(notificationSchema) })
}

export function markNotificationRead(id: string): Promise<Notification> {
  return apiRequest(`/notifications/${id}/read`, { method: "PATCH", schema: notificationSchema })
}

export const NOTIFICATION_POLL_MS = 60_000

// Polled so the bell's unread dot appears without a page reload. There's no
// push channel: notifications are a synchronous log the client reads.
export function useNotifications() {
  return useQuery({
    queryKey: notificationKeys.list(),
    queryFn: listNotifications,
    refetchInterval: NOTIFICATION_POLL_MS,
  })
}

export function useMarkNotificationRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: markNotificationRead,
    // Flip the dot immediately; the refetch on settle confirms it (or reverts on failure).
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: notificationKeys.list() })
      const previous = queryClient.getQueryData<Notification[]>(notificationKeys.list())
      queryClient.setQueryData<Notification[]>(notificationKeys.list(), (rows) =>
        rows?.map((n) => (n.id === id ? { ...n, is_read: true } : n))
      )
      return { previous }
    },
    onError: (_error, _id, context) => {
      if (context?.previous) queryClient.setQueryData(notificationKeys.list(), context.previous)
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: notificationKeys.list() }),
  })
}

export type { Notification }
