import type { Page } from "./client"

/**
 * The offset of the next page for a load-more list, or undefined when there is no next page. With a total
 * (X-Total-Count) it stops exactly when everything is loaded; without one, a short page means the end.
 */
export function nextOffset<T>(allPages: Page<T[]>[], lastPage: Page<T[]>, pageSize: number): number | undefined {
  const loaded = allPages.reduce((sum, page) => sum + page.items.length, 0)
  if (lastPage.items.length === 0) return undefined
  if (lastPage.total !== null) return loaded < lastPage.total ? loaded : undefined
  return lastPage.items.length >= pageSize ? loaded : undefined
}
