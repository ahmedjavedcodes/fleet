import { NextResponse, type NextRequest } from "next/server"
import { env } from "@/lib/env"
import { getServerToken } from "@/lib/auth/token"

// Every browser call to the backend goes through here (CLAUDE.md §5.2,
// plans/02 §3): it attaches the session's Bearer token server-side and
// streams the request and response bodies through untouched, so SSE (plan
// 07) and multipart uploads (fuel receipts, documents) both work unmodified.

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

// Headers that must not be copied verbatim between hops: connection-management
// headers the runtime recomputes itself, plus set-cookie — the backend never
// sets cookies, and forwarding one here could otherwise collide with our own
// session cookie.
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

/** Rejects anything that isn't a single, literal, safe path segment — the
 * path is joined onto our own base URL, never treated as a full URL, so this
 * can't become an open proxy (plans/02 §3). */
function isSafePathSegments(segments: string[]): boolean {
  return segments.every((segment) => segment.length > 0 && segment !== "." && segment !== ".." && !segment.includes("/"))
}

async function proxy(request: NextRequest, path: string[]): Promise<NextResponse> {
  if (!isSafePathSegments(path)) {
    return NextResponse.json({ detail: "Invalid path" }, { status: 400 })
  }

  const method = request.method

  // CSRF: the session cookie is SameSite=Lax, which already blocks most
  // cross-site form/navigation submissions. This is defense in depth for
  // state-changing requests specifically.
  if (!BODYLESS_METHODS.has(method)) {
    const origin = request.headers.get("origin")
    if (origin && origin !== request.nextUrl.origin) {
      return NextResponse.json({ detail: "Cross-origin request rejected" }, { status: 403 })
    }
  }

  const token = await getServerToken()
  if (!token) {
    // No upstream call at all without a session — matches the backend's own
    // 401 shape so the client-side error mapper handles it identically.
    return NextResponse.json({ detail: "Could not validate credentials" }, { status: 401 })
  }

  const upstreamUrl = `${env.API_BASE_URL}/api/v1/${path.join("/")}${request.nextUrl.search}`

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
      // Required by fetch when streaming a ReadableStream request body.
      duplex: hasBody ? "half" : undefined,
    } as RequestInit & { duplex?: "half" })
  } catch {
    return NextResponse.json({ detail: "Could not reach the backend" }, { status: 503 })
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
export async function PUT(request: NextRequest, { params }: RouteContext) {
  return proxy(request, (await params).path)
}
export async function PATCH(request: NextRequest, { params }: RouteContext) {
  return proxy(request, (await params).path)
}
export async function DELETE(request: NextRequest, { params }: RouteContext) {
  return proxy(request, (await params).path)
}
