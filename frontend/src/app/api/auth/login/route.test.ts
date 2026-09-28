// @vitest-environment node
import { NextRequest } from "next/server"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const cookieStore = new Map<string, { value: string; options?: Record<string, unknown> }>()

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({
    get: (name: string) => (cookieStore.has(name) ? { name, value: cookieStore.get(name)!.value } : undefined),
    set: (name: string, value: string, options?: Record<string, unknown>) => {
      cookieStore.set(name, { value, options })
    },
    delete: (name: string) => {
      cookieStore.delete(name)
    },
  })),
}))

function loginRequest(body: unknown): NextRequest {
  return new NextRequest("http://localhost:3000/api/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  })
}

describe("POST /api/auth/login", () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.stubEnv("API_BASE_URL", "http://backend.internal")
    cookieStore.clear()
    fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it("sets an httpOnly session cookie and never returns the token", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ access_token: "jwt-value", token_type: "bearer", expires_in: 3600 }), {
        status: 200,
      })
    )

    const { POST } = await import("./route")
    const response = await POST(loginRequest({ org_slug: "acme", email: "a@acme.dev", password: "secret123" }))
    const body: unknown = await response.json()

    expect(body).toEqual({ ok: true })
    expect(JSON.stringify(body)).not.toContain("jwt-value")

    const cookie = cookieStore.get("fleet_session")
    expect(cookie?.value).toBe("jwt-value")
    expect(cookie?.options).toMatchObject({ httpOnly: true, sameSite: "lax", path: "/", maxAge: 3600 })
  })

  it("passes a backend 401 through unchanged and sets no cookie", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ detail: "Invalid credentials" }), { status: 401 }))

    const { POST } = await import("./route")
    const response = await POST(loginRequest({ org_slug: "acme", email: "a@acme.dev", password: "wrong" }))

    expect(response.status).toBe(401)
    expect(await response.json()).toEqual({ detail: "Invalid credentials" })
    expect(cookieStore.has("fleet_session")).toBe(false)
  })

  it("returns a local 422 without calling the backend when the body fails validation", async () => {
    const { POST } = await import("./route")
    const response = await POST(loginRequest({ org_slug: "Not Valid!", email: "not-an-email", password: "" }))

    expect(response.status).toBe(422)
    expect(fetchMock).not.toHaveBeenCalled()
    const body = (await response.json()) as { detail: unknown }
    expect(Array.isArray(body.detail)).toBe(true)
  })

  it("returns 503 when the backend is unreachable", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"))
    const { POST } = await import("./route")
    const response = await POST(loginRequest({ org_slug: "acme", email: "a@acme.dev", password: "secret123" }))
    expect(response.status).toBe(503)
  })
})
