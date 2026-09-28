// Shared by rbac.ts (route access) and route-labels.ts (breadcrumb/area
// labels) — both key a list of route entries by path prefix and need the
// same "most specific wins" resolution (e.g. /foundation/vehicles over the
// looser parent /foundation).
export function longestPrefixMatch<T extends { prefix: string }>(
  entries: readonly T[],
  pathname: string
): T | undefined {
  return entries
    .filter((entry) => pathname === entry.prefix || pathname.startsWith(`${entry.prefix}/`))
    .sort((a, b) => b.prefix.length - a.prefix.length)[0]
}
