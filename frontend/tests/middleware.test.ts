// @vitest-environment node
import { NextRequest } from "next/server"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

function makeRequest(path: string, opts: { cookie?: string } = {}): NextRequest {
  const headers = new Headers()
  if (opts.cookie) headers.set("cookie", opts.cookie)
  return new NextRequest(new URL(path, "http://localhost:3000"), { headers })
}

describe("middleware", () => {
  beforeEach(() => {
    vi.stubEnv("API_BASE_URL", "http://localhost:8000")
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  it("redirects an unauthenticated request to a protected page, with next= set", async () => {
    const { middleware } = await import("@/middleware")
    const response = middleware(makeRequest("/dashboard?tab=fuel"))
    expect(response.status).toBe(307)
    expect(response.headers.get("location")).toBe("http://localhost:3000/login?next=%2Fdashboard%3Ftab%3Dfuel")
  })

  it("lets an unauthenticated request through to the public /login page", async () => {
    const { middleware } = await import("@/middleware")
    const response = middleware(makeRequest("/login"))
    expect(response.status).not.toBe(307)
    expect(response.headers.get("location")).toBeNull()
  })

  it("redirects an authenticated request away from /login to /dashboard by default", async () => {
    const { middleware } = await import("@/middleware")
    const response = middleware(makeRequest("/login", { cookie: "fleet_session=abc" }))
    expect(response.status).toBe(307)
    expect(response.headers.get("location")).toBe("http://localhost:3000/dashboard")
  })

  it("lets an authenticated request through to a protected page", async () => {
    const { middleware } = await import("@/middleware")
    const response = middleware(makeRequest("/foundation/vehicles", { cookie: "fleet_session=abc" }))
    expect(response.status).not.toBe(307)
    expect(response.headers.get("location")).toBeNull()
  })

  it("honors a safe next= when bouncing an authenticated user off /login", async () => {
    const { middleware } = await import("@/middleware")
    const response = middleware(makeRequest("/login?next=%2Ffoundation%2Fvehicles", { cookie: "fleet_session=abc" }))
    expect(response.headers.get("location")).toBe("http://localhost:3000/foundation/vehicles")
  })

  it("rejects an absolute-URL next= (open-redirect) and falls back to /dashboard", async () => {
    const { middleware } = await import("@/middleware")
    const response = middleware(
      makeRequest(`/login?next=${encodeURIComponent("https://evil.example.com")}`, { cookie: "fleet_session=abc" })
    )
    expect(response.headers.get("location")).toBe("http://localhost:3000/dashboard")
  })

  it("rejects a scheme-relative next= (//host)", async () => {
    const { middleware } = await import("@/middleware")
    const response = middleware(
      makeRequest(`/login?next=${encodeURIComponent("//evil.example.com")}`, { cookie: "fleet_session=abc" })
    )
    expect(response.headers.get("location")).toBe("http://localhost:3000/dashboard")
  })

  it("excludes the proxy, the login BFF route and static assets from the matcher", async () => {
    const { config } = await import("@/middleware")
    const [pattern] = config.matcher
    expect(pattern).toContain("api/proxy")
    expect(pattern).toContain("api/auth/login")
    expect(pattern).toContain("_next/static")
    expect(pattern).toContain("favicon.ico")
  })
})
