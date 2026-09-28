"use client"

import { useEffect, useState } from "react"

// SSR-safe: defaults to `false` (matches the server render and the client's
// first paint before this effect runs), then syncs to the real viewport
// after mount. Consumers that use this to drive a "narrow by default"
// layout (e.g. the sidebar's icon-only mode) get one harmless re-render on
// a wide viewport rather than a hydration mismatch.
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false)

  useEffect(() => {
    const mql = window.matchMedia(query)
    setMatches(mql.matches)
    const handler = (event: MediaQueryListEvent) => setMatches(event.matches)
    mql.addEventListener("change", handler)
    return () => mql.removeEventListener("change", handler)
  }, [query])

  return matches
}
