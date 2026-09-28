import "server-only"
import { cookies } from "next/headers"
import { env } from "@/lib/env"

// Split out of session.ts to break a circular import: session.ts's
// getServerMe() calls lib/api/server-client.ts, which needs the token to
// attach the Authorization header, but session.ts is where the token is
// normally read from. This file has no dependency on server-client.ts, so
// both can import it safely.

export async function getServerToken(): Promise<string | undefined> {
  const store = await cookies()
  return store.get(env.SESSION_COOKIE_NAME)?.value
}
