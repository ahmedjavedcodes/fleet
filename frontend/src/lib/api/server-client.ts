import "server-only"
import type { z } from "zod"
import { env } from "@/lib/env"
import { getServerToken } from "@/lib/auth/token"
import { networkError, schemaError, toApiError, type ApiError } from "./errors"

// The server-only twin of client.ts (plans/02 §5). Server Components that
// prefetch call the backend directly with the session token instead of
// looping back through /api/proxy — same error/schema contract, different
// transport.

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE"
type QueryValue = string | number | boolean | undefined
type Query = Record<string, QueryValue>

interface BaseOptions {
  method?: Method
  body?: unknown
  query?: Query
}

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams()
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) params.set(key, String(value))
    }
  }
  const qs = params.toString()
  return `${env.API_BASE_URL}/api/v1${path}${qs ? `?${qs}` : ""}`
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

const unauthorized: ApiError = { kind: "unauthorized", status: 401 }

export async function serverApiRequest<T>(path: string, options: BaseOptions & { schema: z.ZodType<T> }): Promise<T>
export async function serverApiRequest(path: string, options: BaseOptions & { schema?: undefined }): Promise<void>
export async function serverApiRequest<T>(
  path: string,
  options: BaseOptions & { schema?: z.ZodType<T> }
): Promise<T | void> {
  const { method = "GET", body, query, schema } = options

  const token = await getServerToken()
  if (!token) throw unauthorized

  const headers: Record<string, string> = {
    Accept: "application/json",
    Authorization: `Bearer ${token}`,
  }
  if (body !== undefined) headers["Content-Type"] = "application/json"

  let response: Response
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      // Prefetches feed a live page; never serve a stale cached response.
      cache: "no-store",
    })
  } catch {
    throw networkError()
  }

  if (!response.ok) {
    const errorBody = await parseJsonSafe(response)
    throw toApiError(response.status, errorBody, response.headers)
  }

  if (!schema) return undefined

  const json = response.status === 204 ? undefined : await parseJsonSafe(response)
  const result = schema.safeParse(json)
  if (!result.success) {
    console.error(`Schema validation failed for ${method} ${path}:`, result.error)
    throw schemaError(result.error.message)
  }
  return result.data
}
