// @vitest-environment node
import { NextRequest } from "next/server"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const cookieStore = new Map<string, string>()

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({
    get: (name: string) => (cookieStore.has(name) ? { name, value: cookieStore.get(name)! } : undefined),
  })),
}))

function ctx(path: string[]) {
  return { params: Promise.resolve({ path }) }
}

describe("proxy route", () => {
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
    cookieStore.clear()
  })

  it("returns its own 401 with no upstream call when there's no session cookie", async () => {
    const { GET } = await import("./route")
    const request = new NextRequest("http://localhost:3000/api/proxy/vehicles")
    const response = await GET(request, ctx(["vehicles"]))
    expect(response.status).toBe(401)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("attaches the Bearer token and rebuilds the URL under /api/v1, keeping the query string", async () => {
    cookieStore.set("fleet_session", "jwt-abc")
    fetchMock.mockResolvedValue(new Response("[]", { status: 200, headers: { "content-type": "application/json" } }))

    const { GET } = await import("./route")
    const request = new NextRequest("http://localhost:3000/api/proxy/vehicles?status=active")
    await GET(request, ctx(["vehicles"]))

    const [url, init] = fetchMock.mock.calls[0] as [string, { headers: Headers }]
    expect(url).toBe("http://backend.internal/api/v1/vehicles?status=active")
    expect(init.headers.get("authorization")).toBe("Bearer jwt-abc")
  })

  it("streams a POST body through with duplex: half, forwarding content-type", async () => {
    cookieStore.set("fleet_session", "jwt-abc")
    fetchMock.mockResolvedValue(new Response(null, { status: 201 }))

    const { POST } = await import("./route")
    const request = new NextRequest("http://localhost:3000/api/proxy/vehicles", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ make: "Toyota" }),
    })
    await POST(request, ctx(["vehicles"]))

    const [, init] = fetchMock.mock.calls[0] as [string, { method: string; duplex?: string; body: unknown; headers: Headers }]
    expect(init.method).toBe("POST")
    expect(init.duplex).toBe("half")
    expect(init.body).not.toBeNull()
    expect(init.headers.get("content-type")).toBe("application/json")
  })

  it("attaches no body or duplex for a GET", async () => {
    cookieStore.set("fleet_session", "jwt-abc")
    fetchMock.mockResolvedValue(new Response("[]", { status: 200 }))
    const { GET } = await import("./route")
    const request = new NextRequest("http://localhost:3000/api/proxy/vehicles")
    await GET(request, ctx(["vehicles"]))
    const [, init] = fetchMock.mock.calls[0] as [string, { body?: unknown; duplex?: string }]
    expect(init.body).toBeUndefined()
    expect(init.duplex).toBeUndefined()
  })

  it("rejects a '..' path segment without calling upstream (can't become an open proxy)", async () => {
    cookieStore.set("fleet_session", "jwt-abc")
    const { GET } = await import("./route")
    const request = new NextRequest("http://localhost:3000/api/proxy/vehicles/..")
    const response = await GET(request, ctx(["vehicles", ".."]))
    expect(response.status).toBe(400)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("rejects a state-changing request whose Origin doesn't match this app", async () => {
    cookieStore.set("fleet_session", "jwt-abc")
    const { POST } = await import("./route")
    const request = new NextRequest("http://localhost:3000/api/proxy/vehicles", {
      method: "POST",
      headers: { origin: "https://evil.example.com" },
      body: "{}",
    })
    const response = await POST(request, ctx(["vehicles"]))
    expect(response.status).toBe(403)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("allows a state-changing request whose Origin matches this app", async () => {
    cookieStore.set("fleet_session", "jwt-abc")
    fetchMock.mockResolvedValue(new Response(null, { status: 201 }))
    const { POST } = await import("./route")
    const request = new NextRequest("http://localhost:3000/api/proxy/vehicles", {
      method: "POST",
      headers: { origin: "http://localhost:3000" },
      body: "{}",
    })
    const response = await POST(request, ctx(["vehicles"]))
    expect(response.status).toBe(201)
  })

  it("strips hop-by-hop headers and set-cookie from the upstream response", async () => {
    cookieStore.set("fleet_session", "jwt-abc")
    fetchMock.mockResolvedValue(
      new Response("[]", {
        status: 200,
        headers: {
          "content-type": "application/json",
          "set-cookie": "session=forged; Path=/",
          connection: "keep-alive",
        },
      })
    )
    const { GET } = await import("./route")
    const request = new NextRequest("http://localhost:3000/api/proxy/vehicles")
    const response = await GET(request, ctx(["vehicles"]))
    expect(response.headers.get("set-cookie")).toBeNull()
    expect(response.headers.get("connection")).toBeNull()
    expect(response.headers.get("content-type")).toBe("application/json")
  })

  it("returns 503 when the backend is unreachable", async () => {
    cookieStore.set("fleet_session", "jwt-abc")
    fetchMock.mockRejectedValue(new TypeError("fetch failed"))
    const { GET } = await import("./route")
    const request = new NextRequest("http://localhost:3000/api/proxy/vehicles")
    const response = await GET(request, ctx(["vehicles"]))
    expect(response.status).toBe(503)
  })
})
