import "server-only"
import { cookies } from "next/headers"
import { env } from "@/lib/env"
import { meResponseSchema, type MeResponse } from "@/lib/schemas/auth"
import { serverApiRequest } from "@/lib/api/server-client"
import { getServerToken } from "./token"

// The only place the session cookie is written or deleted (plans/02 §8). The
// JWT itself never reaches client JS — components read the session through
// GET /auth/me only (CLAUDE.md §3), never by decoding this cookie.
export { getServerToken }

/** Route-handler only (Next forbids cookie writes during a Server Component render). */
export async function setServerToken(token: string, maxAgeSeconds: number): Promise<void> {
  const store = await cookies()
  store.set(env.SESSION_COOKIE_NAME, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: maxAgeSeconds,
  })
}

/** Route-handler only, same restriction as setServerToken. */
export async function clearServerToken(): Promise<void> {
  const store = await cookies()
  store.delete(env.SESSION_COOKIE_NAME)
}

/** For Server Components: the current session, or null if signed out or the
 * token is no longer valid. Never throws — callers render an unauthenticated
 * state instead of crashing the page shell. */
export async function getServerMe(): Promise<MeResponse | null> {
  const token = await getServerToken()
  if (!token) return null
  try {
    return await serverApiRequest("/auth/me", { schema: meResponseSchema })
  } catch {
    return null
  }
}
