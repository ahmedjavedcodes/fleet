import { NextRequest, NextResponse } from "next/server";

import { AUTH_COOKIE_NAME } from "@/lib/auth-shared";

// Cheap presence check only — the middleware runs on the edge and can't
// verify the JWT signature without pulling in a jwt library there. Real
// authorization still happens per-request on the backend; this just keeps
// signed-out users from landing on a page that will immediately 401.
const PUBLIC_PATHS = ["/login"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isPublic = PUBLIC_PATHS.some((path) => pathname.startsWith(path));
  const hasToken = request.cookies.has(AUTH_COOKIE_NAME);

  if (!isPublic && !hasToken) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  if (isPublic && hasToken) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
