// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const cookieStore = new Map<string, string>()

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({
    get: (name: string) => (cookieStore.has(name) ? { name, value: cookieStore.get(name)! } : undefined),
    set: (name: string, value: string) => {
      cookieStore.set(name, value)
    },
    delete: (name: string) => {
      cookieStore.delete(name)
    },
  })),
}))

describe("POST /api/auth/logout", () => {
  beforeEach(() => {
    vi.stubEnv("API_BASE_URL", "http://backend.internal")
    cookieStore.set("fleet_session", "some-jwt")
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    cookieStore.clear()
    vi.resetModules()
  })

  it("clears the session cookie and returns 204 (the backend has no logout endpoint to call)", async () => {
    const { POST } = await import("./route")
    const response = await POST()
    expect(response.status).toBe(204)
    expect(cookieStore.has("fleet_session")).toBe(false)
  })
})
