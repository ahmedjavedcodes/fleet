import { NextResponse, type NextRequest } from "next/server"
import { env } from "@/lib/env"
import { getServerToken } from "@/lib/auth/token"

// The ai_agents chat server's own proxy (mirrors api/proxy/[...path] exactly,
// down to the CSRF/header handling) — a separate process/port from the main
// backend, so it needs its own upstream base URL. Streams both directions
// untouched, which is what makes the SSE chat stream pass through unbuffered.

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

const DROPPED_RESPONSE_HEADERS = new Set([
  "connection",
  "keep-alive",
  "transfer-encoding",
  "upgrade",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "trailers",
  "content-encoding",
  "content-length",
  "set-cookie",
])

const BODYLESS_METHODS = new Set(["GET", "HEAD"])

function isSafePathSegments(segments: string[]): boolean {
  return segments.every((segment) => segment.length > 0 && segment !== "." && segment !== ".." && !segment.includes("/"))
}

async function proxy(request: NextRequest, path: string[]): Promise<NextResponse> {
  if (!isSafePathSegments(path)) {
    return NextResponse.json({ detail: "Invalid path" }, { status: 400 })
  }

  const method = request.method

  if (!BODYLESS_METHODS.has(method)) {
    const origin = request.headers.get("origin")
    if (origin && origin !== request.nextUrl.origin) {
      return NextResponse.json({ detail: "Cross-origin request rejected" }, { status: 403 })
    }
  }

  const token = await getServerToken()
  if (!token) {
    return NextResponse.json({ detail: "Could not validate credentials" }, { status: 401 })
  }

  const upstreamUrl = `${env.AGENTS_API_BASE_URL}/api/v1/${path.join("/")}${request.nextUrl.search}`

  const headers = new Headers()
  const contentType = request.headers.get("content-type")
  if (contentType) headers.set("content-type", contentType)
  const accept = request.headers.get("accept")
  if (accept) headers.set("accept", accept)
  headers.set("authorization", `Bearer ${token}`)

  const hasBody = !BODYLESS_METHODS.has(method)

  let upstream: Response
  try {
    upstream = await fetch(upstreamUrl, {
      method,
      headers,
      body: hasBody ? request.body : undefined,
      duplex: hasBody ? "half" : undefined,
    } as RequestInit & { duplex?: "half" })
  } catch {
    return NextResponse.json({ detail: "Could not reach the AI assistant" }, { status: 503 })
  }

  const responseHeaders = new Headers()
  upstream.headers.forEach((value, key) => {
    if (!DROPPED_RESPONSE_HEADERS.has(key.toLowerCase())) {
      responseHeaders.set(key, value)
    }
  })

  return new NextResponse(upstream.body, { status: upstream.status, headers: responseHeaders })
}

type RouteContext = { params: Promise<{ path: string[] }> }

export async function GET(request: NextRequest, { params }: RouteContext) {
  return proxy(request, (await params).path)
}
export async function POST(request: NextRequest, { params }: RouteContext) {
  return proxy(request, (await params).path)
}
