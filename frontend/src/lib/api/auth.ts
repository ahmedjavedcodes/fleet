import { meResponseSchema, type LoginRequest, type MeResponse } from "@/lib/schemas/auth"
import { apiRequest } from "./client"
import { networkError, toApiError } from "./errors"

// login() and logout() call the Next BFF routes directly, not /api/proxy —
// those routes *are* the auth boundary (they set/clear the session cookie),
// not a backend passthrough (CLAUDE.md §5.2).

export async function login(input: LoginRequest): Promise<void> {
  let response: Response
  try {
    response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
      credentials: "same-origin",
    })
  } catch {
    throw networkError()
  }

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => undefined)
    throw toApiError(response.status, body, response.headers)
  }
}

export async function logout(): Promise<void> {
  try {
    await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" })
  } catch {
    // Sign-out proceeds regardless — the caller clears local query state and
    // navigates to /login either way (there's no server session to fail to
    // clear if this request itself failed to reach the server).
  }
}

export function getMe(): Promise<MeResponse> {
  return apiRequest("/auth/me", { schema: meResponseSchema })
}
