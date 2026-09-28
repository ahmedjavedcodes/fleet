import { NextResponse, type NextRequest } from "next/server"
import { env } from "@/lib/env"
import { setServerToken } from "@/lib/auth/session"
import { loginRequestSchema, tokenResponseSchema } from "@/lib/schemas/auth"

// BFF login (CLAUDE.md §5.2, plans/02 §3). Forwards {org_slug, email,
// password} to the backend and, on success, stores the JWT in an httpOnly
// cookie. The response body never contains the token — client JS only ever
// learns whether login succeeded.

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

export async function POST(request: NextRequest) {
  let body: unknown
  try {
    body = await request.json()
  } catch {
    return NextResponse.json({ detail: "Invalid request body" }, { status: 400 })
  }

  const parsed = loginRequestSchema.safeParse(body)
  if (!parsed.success) {
    return NextResponse.json(
      { detail: parsed.error.issues.map((issue) => ({ loc: issue.path, msg: issue.message })) },
      { status: 422 }
    )
  }

  let upstream: Response
  try {
    upstream = await fetch(`${env.API_BASE_URL}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(parsed.data),
      cache: "no-store",
    })
  } catch {
    return NextResponse.json({ detail: "Could not reach the authentication server" }, { status: 503 })
  }

  const json: unknown = await upstream.json().catch(() => undefined)

  if (!upstream.ok) {
    // Backend 401 ("Invalid credentials") / 422 pass through with the same
    // status and shape (plans/02 §3).
    return NextResponse.json(json ?? { detail: "Login failed" }, { status: upstream.status })
  }

  const token = tokenResponseSchema.safeParse(json)
  if (!token.success) {
    return NextResponse.json({ detail: "Unexpected response from the authentication server" }, { status: 502 })
  }

  await setServerToken(token.data.access_token, token.data.expires_in)

  return NextResponse.json({ ok: true })
}
