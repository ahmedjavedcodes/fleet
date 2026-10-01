import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData } from "@tanstack/react-query"
import { z } from "zod"
import { notificationKeys } from "@/lib/query/keys"
import { notificationSchema, type Notification } from "@/lib/schemas/notification"
import { apiRequest } from "./client"
import { nextOffset } from "./paging"

// The signed-in user's own notifications. Every role has them; the backend
// never returns anyone else's.

export function listNotifications(query?: {
  type?: Notification["type"]
  unreadOnly?: boolean
  limit?: number
  offset?: number
}): Promise<Notification[]> {
  return apiRequest("/notifications", {
    query: { type: query?.type, unread_only: query?.unreadOnly, limit: query?.limit, offset: query?.offset },
    schema: z.array(notificationSchema),
  })
}

export const NOTIFICATION_PAGE_SIZE = 25
// The bell only previews a few and needs to know whether anything is unread; neither warrants the whole feed.
const BELL_PREVIEW_LIMIT = 10

export function markNotificationRead(id: string): Promise<Notification> {
  return apiRequest(`/notifications/${id}/read`, { method: "PATCH", schema: notificationSchema })
}

export const NOTIFICATION_POLL_MS = 60_000

// Polled so the bell's unread dot appears without a page reload. There's no
// push channel: notifications are a synchronous log the client reads.
export function useNotifications(options?: { limit?: number }) {
  const limit = options?.limit ?? BELL_PREVIEW_LIMIT
  return useQuery({
    queryKey: notificationKeys.list(limit),
    queryFn: () => listNotifications({ unreadOnly: true, limit }),
    refetchInterval: NOTIFICATION_POLL_MS,
  })
}

/** Whether any stored notification is unread: one row asked for, so the bell's dot costs almost nothing. */
export function useHasUnreadNotifications() {
  return useQuery({
    queryKey: notificationKeys.unread(),
    queryFn: () => listNotifications({ unreadOnly: true, limit: 1 }),
    select: (rows) => rows.length > 0,
    refetchInterval: NOTIFICATION_POLL_MS,
  })
}

/** One tab of the notifications page (unread only: tapped ones vanish), loaded page by page ("Load more"): warnings or events. */
export function useNotificationPages(type: Notification["type"]) {
  return useInfiniteQuery({
    queryKey: notificationKeys.pages(type),
    queryFn: ({ pageParam }) => listNotifications({ type, unreadOnly: true, limit: NOTIFICATION_PAGE_SIZE, offset: pageParam }),
    initialPageParam: 0,
    // This list sends no total: a full page means there may be more.
    getNextPageParam: (last, all) =>
      nextOffset(
        all.map((items) => ({ items, total: null })),
        { items: last, total: null },
        NOTIFICATION_PAGE_SIZE
      ),
    select: (data) => data.pages.flat(),
    refetchInterval: NOTIFICATION_POLL_MS,
  })
}

export function useMarkNotificationRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: markNotificationRead,
    // Flip the dot immediately; the refetch on settle confirms it (or reverts on failure).
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: notificationKeys.all })
      const previousLists = queryClient.getQueriesData<Notification[]>({ queryKey: notificationKeys.list() })
      const previousPages = queryClient.getQueriesData<InfiniteData<Notification[]>>({ queryKey: notificationKeys.pages() })
      // The lists show unread entries only: a tapped one disappears at once (the refetch on settle confirms it).
      queryClient.setQueriesData<Notification[]>({ queryKey: notificationKeys.list() }, (rows) => rows?.filter((n) => n.id !== id))
      queryClient.setQueriesData<InfiniteData<Notification[]>>({ queryKey: notificationKeys.pages() }, (data) =>
        data ? { ...data, pages: data.pages.map((page) => page.filter((n) => n.id !== id)) } : data
      )
      return { previousLists, previousPages }
    },
    onError: (_error, _id, context) => {
      for (const [key, data] of context?.previousLists ?? []) queryClient.setQueryData(key, data)
      for (const [key, data] of context?.previousPages ?? []) queryClient.setQueryData(key, data)
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: notificationKeys.all }),
  })
}

export type { Notification }
