// Single entry point for all backend HTTP calls (CLAUDE.md #3). Every
// resource-specific helper (getVehicles, createIncident, ...) should be a
// thin wrapper around apiFetch, not a raw fetch() call.
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// Shape of a FastAPI/Pydantic 422 response body.
interface ValidationErrorDetail {
  loc: (string | number)[];
  msg: string;
  type: string;
}

export type ApiErrorKind = "unauthorized" | "forbidden" | "conflict" | "validation" | "not_found" | "server" | "network";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly fieldErrors: Record<string, string>;

  constructor(kind: ApiErrorKind, message: string, status: number | null, fieldErrors: Record<string, string> = {}) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.fieldErrors = fieldErrors;
  }
}

function kindForStatus(status: number): ApiErrorKind {
  switch (status) {
    case 401:
      return "unauthorized";
    case 403:
      return "forbidden";
    case 404:
      return "not_found";
    case 409:
      return "conflict";
    case 422:
      return "validation";
    default:
      return "server";
  }
}

function fieldErrorsFromDetail(detail: unknown): Record<string, string> {
  if (!Array.isArray(detail)) return {};
  const errors: Record<string, string> = {};
  for (const item of detail as ValidationErrorDetail[]) {
    // loc is typically ["body", "field_name"] — drop the "body"/"query" prefix.
    const field = item.loc[item.loc.length - 1];
    if (typeof field === "string") errors[field] = item.msg;
  }
  return errors;
}

export interface ApiFetchOptions extends RequestInit {
  /** Bearer token to attach. Callers resolve this from auth-server.ts (Server
   * Components) or auth-client.ts (Client Components) — apiFetch itself never
   * touches cookies/localStorage so it stays usable from either context. */
  token?: string | null;
}

export async function apiFetch<T>(path: string, { token, headers, ...init }: ApiFetchOptions = {}): Promise<T> {
  const isFormData = init.body instanceof FormData;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        // Skip Content-Type for FormData — the browser must set the
        // multipart boundary itself; a manual header here would break it.
        ...(isFormData ? {} : { "Content-Type": "application/json" }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
    });
  } catch {
    throw new ApiError("network", "Could not reach the server. Check your connection and try again.", null);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const isJson = response.headers.get("content-type")?.includes("application/json");
  const body = isJson ? await response.json().catch(() => null) : null;

  if (!response.ok) {
    const kind = kindForStatus(response.status);
    const detail = body?.detail;
    const message = typeof detail === "string" ? detail : response.statusText || "Request failed";
    throw new ApiError(kind, message, response.status, kind === "validation" ? fieldErrorsFromDetail(detail) : {});
  }

  return body as T;
}

/** For multipart/form-data uploads (receipts, incident photos, agent vision
 * input). Never set Content-Type manually — the browser must set the
 * multipart boundary itself. */
export async function apiUpload<T>(path: string, formData: FormData, token?: string | null): Promise<T> {
  return apiFetch<T>(path, { method: "POST", body: formData, token, headers: {} });
}
