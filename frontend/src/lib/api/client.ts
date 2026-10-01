import type { z } from "zod"
import { networkError, schemaError, toApiError } from "./errors"

// The only place in browser code that calls fetch (CLAUDE.md §5.2). Every
// domain module (lib/api/vehicles.ts, …) calls apiRequest instead of fetch
// directly. Requests go through /api/proxy/[...path], which attaches the
// Bearer token server-side — client JS never sees or sends the JWT itself.
// Client-only: Server Components prefetch through lib/api/server-client.ts
// instead, which talks to the backend directly with the session token.

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE"
type QueryValue = string | number | boolean | undefined
type Query = Record<string, QueryValue>

interface BaseOptions {
  method?: Method
  body?: unknown
  query?: Query
  signal?: AbortSignal
}

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams()
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) params.set(key, String(value))
    }
  }
  const qs = params.toString()
  return `/api/proxy${path}${qs ? `?${qs}` : ""}`
}

async function parseJsonSafe(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text) return undefined
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

/** One page of a list plus the total number of rows across all pages (the backend's X-Total-Count header), or null when the endpoint doesn't send it. */
export type Page<T> = { items: T; total: number | null }

/** A list request whose response is one page: the body is validated like any other, and the total comes from X-Total-Count. */
export async function apiRequestPage<T>(path: string, options: BaseOptions & { schema: z.ZodType<T> }): Promise<Page<T>> {
  const { items, response } = await send<T>(path, options)
  const header = response.headers.get("X-Total-Count")
  const total = header !== null && /^\d+$/.test(header) ? Number(header) : null
  return { items, total }
}

/** Requests that return a parsed, schema-validated body. */
export async function apiRequest<T>(path: string, options: BaseOptions & { schema: z.ZodType<T> }): Promise<T>
/** Requests with no response body to validate (e.g. a 204 DELETE). */
export async function apiRequest(path: string, options: BaseOptions & { schema?: undefined }): Promise<void>
export async function apiRequest<T>(
  path: string,
  options: BaseOptions & { schema?: z.ZodType<T> }
): Promise<T | void> {
  if (!options.schema) {
    await send(path, options)
    return undefined
  }
  return (await send<T>(path, options as BaseOptions & { schema: z.ZodType<T> })).items
}

async function send<T>(
  path: string,
  options: BaseOptions & { schema?: z.ZodType<T> }
): Promise<{ items: T; response: Response }> {
  const { method = "GET", body, query, signal, schema } = options

  const isFormData = typeof FormData !== "undefined" && body instanceof FormData
  const headers: Record<string, string> = { Accept: "application/json" }
  if (body !== undefined && !isFormData) headers["Content-Type"] = "application/json"

  let response: Response
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers,
      body: body === undefined ? undefined : isFormData ? (body as FormData) : JSON.stringify(body),
      signal,
      // Same-origin: the session cookie is httpOnly and read server-side by
      // the proxy route, never by this client code.
      credentials: "same-origin",
    })
  } catch {
    throw networkError()
  }

  if (!response.ok) {
    const errorBody = await parseJsonSafe(response)
    throw toApiError(response.status, errorBody, response.headers)
  }

  if (!schema) return { items: undefined as T, response }

  const json = response.status === 204 ? undefined : await parseJsonSafe(response)
  const result = schema.safeParse(json)
  if (!result.success) {
    console.error(`Schema validation failed for ${method} ${path}:`, result.error)
    throw schemaError(result.error.message)
  }
  return { items: result.data, response }
}
