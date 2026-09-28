import { NextResponse, type NextRequest } from "next/server"
import { env } from "@/lib/env"
import { safeNextPath } from "@/lib/auth/safe-next-path"

// Redirects unauthenticated users to /login (CLAUDE.md §5.2, plans/02 §4).
// Only checks that the session cookie *exists* — it does not verify the JWT
// at the edge. The backend is the security boundary (CLAUDE.md non-negotiable
// #3); every 401/403 from an actual API call is still handled by the error
// mapper regardless of what middleware decided here.

const PUBLIC_PATHS = ["/login"]

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`))
}

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl
  const hasSession = request.cookies.has(env.SESSION_COOKIE_NAME)

  if (!hasSession && !isPublicPath(pathname)) {
    const loginUrl = new URL("/login", request.url)
    loginUrl.searchParams.set("next", `${pathname}${search}`)
    return NextResponse.redirect(loginUrl, 307)
  }

  if (hasSession && pathname === "/login") {
    const next = safeNextPath(request.nextUrl.searchParams.get("next"))
    return NextResponse.redirect(new URL(next ?? "/dashboard", request.url), 307)
  }

  return NextResponse.next()
}

export const config = {
  // The proxy and the login BFF route return their own 401s and must never
  // be intercepted by an HTML redirect; static assets are excluded as usual.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api/proxy|api/auth/login).*)"],
}
