// Shared by middleware.ts and the login page's post-login redirect (plans/02
// §4, §10). Only a root-relative, same-origin path is honored — never an
// absolute URL or a "//host"-style scheme-relative one — so a `?next=`
// query param can never send someone off-site (open-redirect prevention).
// No server-only dependency: this runs in edge middleware and client code.
export function safeNextPath(next: string | null | undefined): string | null {
  if (!next) return null
  if (!next.startsWith("/") || next.startsWith("//")) return null
  if (next.includes("\\") || next.includes("://")) return null
  return next
}
