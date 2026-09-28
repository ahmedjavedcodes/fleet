// Central error mapper (CLAUDE.md §5.3, plans/02 §5). Every response lib/api/
// client.ts doesn't parse successfully becomes one of these, and every page's
// ErrorState / form switches on `.kind` rather than inspecting status codes
// itself.

export type ApiError =
  | { kind: "unauthorized"; status: 401 }
  | { kind: "forbidden"; status: 403; message: string }
  | { kind: "not_found"; status: 404; message: string }
  | { kind: "conflict"; status: 409; message: string }
  // Business-rule rejections (odometer not increasing, vehicle/driver not
  // active, …) — always has a human message from the backend.
  | { kind: "bad_request"; status: 400; message: string }
  | { kind: "validation"; status: 422; message: string; fieldErrors: Record<string, string> }
  | { kind: "rate_limited"; status: 429; message: string; retryAfter?: number }
  | { kind: "payload_too_large"; status: 413 }
  | { kind: "unsupported_media"; status: 415 }
  | { kind: "unavailable"; status: 503; message: string }
  | { kind: "server"; status: number }
  | { kind: "network" }
  // A response parsed as JSON but failed its zod schema — never silently
  // ignored (CLAUDE.md §5.2). Details go to the console only, never to users.
  | { kind: "schema"; issues: string }

export function isApiError(value: unknown): value is ApiError {
  return typeof value === "object" && value !== null && "kind" in value
}

// FastAPI's 422 `detail` is normally `[{type, loc, msg, input, ctx?}]`, but at
// least one backend route (POST /fuel for a driver with no linked profile)
// returns a plain string `detail` on a 422 too — the parser must accept both
// (plans/02 §1).
type PydanticValidationError = { loc: (string | number)[]; msg: string; type?: string }

function isValidationErrorArray(detail: unknown): detail is PydanticValidationError[] {
  return (
    Array.isArray(detail) &&
    detail.every((d) => d && typeof d === "object" && Array.isArray((d as PydanticValidationError).loc))
  )
}

function extractDetail(body: unknown): string | PydanticValidationError[] | undefined {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === "string") return detail
    if (isValidationErrorArray(detail)) return detail
  }
  return undefined
}

function fallbackMessage(status: number): string {
  return `Request failed (${status}).`
}

/** Builds `{ field: message }` from a Pydantic 422 detail array, using the
 * last `loc` segment as the field name (e.g. ["body", "odometer_reading"] → "odometer_reading"). */
function buildFieldErrors(detail: PydanticValidationError[]): Record<string, string> {
  const fieldErrors: Record<string, string> = {}
  for (const issue of detail) {
    const field = issue.loc[issue.loc.length - 1]
    if (field !== undefined) fieldErrors[String(field)] = issue.msg
  }
  return fieldErrors
}

/** Converts an HTTP response (with its already-attempted-JSON body) into an ApiError. */
export function toApiError(status: number, body: unknown, headers?: Headers): ApiError {
  const detail = extractDetail(body)
  const message = typeof detail === "string" ? detail : fallbackMessage(status)

  switch (status) {
    case 401:
      return { kind: "unauthorized", status: 401 }
    case 403:
      return { kind: "forbidden", status: 403, message }
    case 404:
      return { kind: "not_found", status: 404, message }
    case 409:
      return { kind: "conflict", status: 409, message }
    case 400:
      return { kind: "bad_request", status: 400, message }
    case 422: {
      const fieldErrors = isValidationErrorArray(detail) ? buildFieldErrors(detail) : {}
      return { kind: "validation", status: 422, message, fieldErrors }
    }
    case 429: {
      const retryAfterHeader = headers?.get("Retry-After")
      const retryAfter = retryAfterHeader ? Number(retryAfterHeader) : undefined
      return { kind: "rate_limited", status: 429, message, retryAfter: Number.isFinite(retryAfter) ? retryAfter : undefined }
    }
    case 413:
      return { kind: "payload_too_large", status: 413 }
    case 415:
      return { kind: "unsupported_media", status: 415 }
    case 503:
      return { kind: "unavailable", status: 503, message }
    default:
      return { kind: "server", status }
  }
}

export function networkError(): ApiError {
  return { kind: "network" }
}

export function schemaError(issues: string): ApiError {
  return { kind: "schema", issues }
}

/** A human, generic-safe message for statuses the mapper doesn't special-case
 * further in a given UI (network/schema/5xx) — never a raw stack trace. */
export function genericErrorMessage(error: ApiError): string {
  switch (error.kind) {
    case "network":
      return "Couldn't reach the server. Check your connection and try again."
    case "schema":
      return "The server returned an unexpected response."
    case "server":
      return "Something went wrong on our end. Please try again."
    case "unauthorized":
      return "Your session has expired. Please sign in again."
    case "payload_too_large":
      return "That file is too large."
    case "unsupported_media":
      return "That file type isn't supported."
    default:
      return error.message
  }
}
