# 02 — Auth (BFF) & API Layer

**Goal:** a secure session (the JWT never reaches client JS), one typed and zod-validated path
to every backend endpoint, a central error mapper, query-key factories, and an RBAC matrix
that mirrors the backend. After this phase, pages only ever call hooks.

**Depends on:** 01. **Unblocks:** 03 onwards.

---

## 1. Backend facts this phase is built on

| Fact | Consequence |
| --- | --- |
| `POST /api/v1/auth/login` takes JSON `{org_slug, email, password}` (not an OAuth2 form) | The login form has three fields. The org slug is required because emails are unique only per org. |
| Response `{access_token, token_type: "bearer", expires_in: 3600}` | Cookie `maxAge = expires_in`. |
| HS256 JWT with claims `sub`, `org`, `role`, `exp`. **No refresh token, no logout endpoint.** | Logout = delete the cookie. When the token expires, the next request gets 401 → redirect to `/login?next=`. |
| Every login failure → 401 `"Invalid credentials"` | A single form-level error; never hint which field was wrong. |
| The role is re-read from the DB on every request | Refetch `/auth/me` on window focus so a role change shows up without re-login. |
| `GET /auth/me` → `{user, organization, driver_profile \| null}` | The only source of name, role and org (CLAUDE.md §3: never decode the JWT). |
| Errors: `{"detail": "<string>"}`, and on 422 `{"detail": [{type, loc, msg, input, ctx?}]}` | **But** `POST /fuel` for a driver with no profile returns a 422 whose `detail` is a *string*. The parser must accept both shapes. |
| Decimals (costs, liters, `cost_per_km`, `reliability_score`) are JSON **strings**, e.g. `"12.3400"` | Parse with a single helper; never do float math on money. |
| Lists are plain arrays with no total. Only `GET /fuel` takes `skip`/`limit` (max 500). | Client-side pagination and sorting elsewhere (CLAUDE.md §1.3: paginate beyond 50 rows). |
| Create/update schemas reject unknown fields (`extra_forbidden`) | Zod request schemas must be `.strict()` and match exactly. |

## 2. Environment

| Variable | Where | Purpose |
| --- | --- | --- |
| `API_BASE_URL` | **server-only** (BFF route handlers) | Backend origin, e.g. `http://localhost:8000`. |
| `NEXT_PUBLIC_API_BASE_URL` | already in `.env.example` | Kept for parity with CLAUDE.md §5.2. **The browser does not use it**: all browser calls go through `/api/proxy`. |
| `SESSION_COOKIE_NAME` | server-only, optional | Default `fleet_session`. |

Add `API_BASE_URL` to `.env.example`. Read env through `src/lib/env.ts` (zod-parsed,
`server-only`) so a missing variable fails at boot, not at the first request.

## 3. BFF route handlers

All live under `src/app/api/`, and all import `server-only` helpers from `src/lib/auth/session.ts`.

| Route | Behavior |
| --- | --- |
| `POST /api/auth/login` | Validates the body with `loginRequestSchema` and forwards it to the backend. On 200, sets cookie `fleet_session=<jwt>` with `httpOnly`, `secure` (in production), `sameSite: "lax"`, `path: "/"`, `maxAge: expires_in`. Returns `{ ok: true }`, **never the token**. Backend 401/422 pass through as `{ detail }` with the same status. |
| `POST /api/auth/logout` | Deletes the cookie → 204. |
| `GET /api/auth/me` | Not needed: `/auth/me` goes through the proxy like everything else. |
| `ALL /api/proxy/[...path]` | Rebuilds `${API_BASE_URL}/api/v1/${path}${search}` and attaches `Authorization: Bearer <cookie>`. Forwards method, body **as a stream** (`duplex: "half"`), `content-type` (so multipart boundaries survive) and `accept`. Returns the upstream `Response` body as a stream, with status and relevant headers, so **SSE and file responses pass through untouched** (needed by plan 07). No cookie → 401 without calling upstream. Strips hop-by-hop headers. Sets `export const dynamic = "force-dynamic"` and uses the Node runtime. |

**Security notes:**

- The proxy only forwards to `/api/v1/*` on `API_BASE_URL`. The path is joined, never taken
  as a full URL, so it can't become an open proxy.
- CSRF: the cookie is SameSite=Lax. On top of that, the proxy rejects state-changing
  methods whose `Origin` header doesn't match the app origin.

## 4. Middleware: `src/middleware.ts`

- Public paths: `/login` and `/api/auth/login`.
- No session cookie on a non-public page → `307` to `/login?next=<pathname+search>`.
- Session cookie on `/login` → `307` to `/dashboard`.
- It only checks that the cookie exists (it doesn't verify the JWT at the edge). The backend
  is the security boundary.
- Matcher excludes `_next/static`, `_next/image`, `favicon.ico` and the `/api/proxy` path
  (the proxy returns its own 401).
- `next` is only honored if it is a same-origin relative path (prevents open redirects).

## 5. `src/lib/api/`

```
lib/api/
├── client.ts        # apiRequest<T>(path, { method, body, query, schema, signal })
├── errors.ts        # ApiError union + toApiError(response | unknown)
├── decimal.ts       # parseDecimal(), formatMoney(), formatNumber()
├── auth.ts          # login(), logout(), getMe()
├── vehicles.ts      # listVehicles, getVehicle, createVehicle, updateVehicle, deleteVehicle,
│                    # getVehicleTimeline, getVehicleCompliance, getVehicleAssignments,
│                    # assignVehicle, releaseVehicle
├── drivers.ts       # list/get/create/update/delete, getDriverTimeline, getDriverAssignments
├── suppliers.ts  fuel.ts  trips.ts  maintenance.ts  compliance.ts  inventory.ts
├── purchase-orders.ts  incidents.ts  driver-reports.ts  dashboard.ts
└── (plan 07) documents.ts  memory.ts  chat.ts  notifications.ts  insights.ts
```

**`client.ts`:**

- The **only** place that calls `fetch`. It prefixes `/api/proxy`, serializes the query
  (skipping `undefined`), sets JSON `content-type` except for `FormData`, and returns
  `undefined` on 204.
- Every successful body is parsed with the caller's zod schema. A parse failure throws
  `ApiError { kind: "schema" }`, which surfaces through the error state (CLAUDE.md §5.2).
- Server Components that prefetch call the backend directly with the cookie token through a
  `server-only` twin (`lib/api/server-client.ts`), so they don't loop back through the proxy.

**`errors.ts`** is a discriminated union that the ErrorState component switches on:

```ts
type ApiError =
  | { kind: "unauthorized"; status: 401 }
  | { kind: "forbidden"; status: 403; message: string }
  | { kind: "not_found"; status: 404; message: string }
  | { kind: "conflict"; status: 409; message: string }
  | { kind: "bad_request"; status: 400; message: string }          // business rules (odometer not increasing…)
  | { kind: "validation"; status: 422; message: string; fieldErrors: Record<string, string> }
  | { kind: "rate_limited"; status: 429; message: string; retryAfter?: number }
  | { kind: "payload_too_large"; status: 413 } | { kind: "unsupported_media"; status: 415 }
  | { kind: "unavailable"; status: 503; message: string }
  | { kind: "server"; status: number } | { kind: "network" } | { kind: "schema"; issues: string };
```

On a 422, `fieldErrors` is built from `detail[].loc`, using the last element as the field name.
If `detail` is a string, `fieldErrors` is empty and `message` is that string. The logic is
salvaged from the reset scaffold: `git show 8424051:frontend/src/lib/api-client.ts`.

**`decimal.ts`:**

- `parseDecimal(s)` returns a `number` for display, or a string-safe value for comparisons.
- Money is formatted with `Intl.NumberFormat(locale, { style: "currency", currency: "PKR" })`.
- Totals are **never** summed client-side; the backend supplies them.

## 6. `src/lib/schemas/`

One file per backend schema module. Each file holds response schemas and `.strict()` request
schemas, and exports only `z.infer` types; never hand-write a duplicate type.

- `enums.ts` mirrors `backend/app/models/enums.py` **exactly**:
  - SubscriptionTier: `trial | starter | pro | enterprise`
  - UserRole: `admin | fleet_manager | driver | mechanic`
  - DriverStatus: `active | suspended | inactive`
  - VehicleFuelType: `diesel | petrol | hybrid | electric`
  - VehicleStatus: `active | maintenance | retired`
  - FuelReceiptUploadStatus: `pending | parsed | failed`
  - PurchaseOrderStatus: `pending | shipped | received | cancelled`
  - ServiceType: `oil_change | brake_service | tire_rotation | engine_repair | transmission | electrical | body_work | general_inspection | other`
  - VehicleCondition: `good | fair | poor`
  - IncidentType: `damage | violation | near_miss`
  - IncidentSeverity: `minor | moderate | severe | critical`
  - IncidentResolutionStatus: `open | investigating | resolved | closed`
  - Schema literals:
    - compliance status: `compliant | due_soon | overdue | never_performed`
    - calendar status: `upcoming | overdue`
    - timeline `record_type`: `trip | report | incident`
- Decimal fields use a shared `decimalString` schema (`z.string().regex(...)`).
- Dates use `z.string().date()`, datetimes `z.string().datetime({ offset: true })`, IDs
  `z.string().uuid()`.
- `TimelineEntry.summary` is a discriminated union on `record_type`.

## 7. `src/lib/query/`

- `client.ts`, `makeQueryClient()`:
  - `staleTime: 30_000`, `refetchOnWindowFocus: true`;
  - `retry: (count, err) => isApiError(err) && err.status >= 400 && err.status < 500 ? false : count < 2`;
  - exponential `retryDelay`;
  - a global `QueryCache.onError`: on `unauthorized`, redirect to `/login?next=` once.
- `keys.ts` holds one factory per domain:

  ```ts
  export const vehicleKeys = {
    all: ["vehicles"] as const,
    list: () => [...vehicleKeys.all, "list"] as const,
    detail: (id: string) => [...vehicleKeys.all, "detail", id] as const,
    timeline: (id: string) => [...vehicleKeys.all, id, "timeline"] as const,
    compliance: (id: string) => [...vehicleKeys.all, id, "compliance"] as const,
    assignments: (id: string, date?: string) => [...vehicleKeys.all, id, "assignments", { date }] as const,
  };
  ```

  Same pattern for `driverKeys`, `fuelKeys` (list(filters), summary(month)), `tripKeys`,
  `maintenanceKeys`, `complianceKeys`, `incidentKeys`, `dashboardKeys`, `meKeys`, …
- Hooks live next to the domain (`lib/api/vehicles.ts` exports `useVehicles()`,
  `useVehicle(id)`, `useAssignVehicle()`, …) or in `lib/hooks/`. **Pick one convention in
  this phase and record it in CLAUDE.md §2.3.** The recommendation is hooks co-located in
  the domain module, so the whole domain lives in one file.
- Mutation invalidation rules come from CLAUDE.md §5.1 (assignment → vehicle and driver
  histories plus dashboard; fuel → fuel lists, summary and dashboard trends; …).

## 8. `src/lib/auth/`

- `session.ts` (`server-only`): cookie get/set/delete, and `getServerMe()` for Server Components.
- `use-current-user.ts`: `useQuery(meKeys.current(), getMe)`, returning `{ user, organization, driverProfile, role }`.
- `role-labels.ts`: `admin → "Admin"`, `fleet_manager → "Fleet Manager"`, `mechanic → "Mechanic"`, `driver → "Driver"`.

## 9. `src/lib/rbac.ts`

`can(role, action): boolean` plus `routeAccess(role, pathname)`. The matrix is taken
**from the backend role gates** (`backend/app/api/*.py`, verified against the `require_role(...)`
tuples on the `frontend` branch). Re-verify whenever the backend changes (CLAUDE.md §8).

| Action | A | FM | M | D |
| --- | :-: | :-: | :-: | :-: |
| `vehicle:read`, `vehicle:timeline`, `vehicle:compliance` | ✓ | ✓ | ✓ | ✓ |
| `vehicle:write` (create/update/delete) | ✓ | ✓ | | |
| `vehicle:assign`, `vehicle:release` | ✓ | ✓ | | |
| `vehicle:assignments:read` | ✓ | ✓ | | ✓ |
| `driver:read` | ✓ | ✓ | ✓ | ✓ |
| `driver:write` | ✓ | ✓ | | |
| `driver:timeline`, `driver:assignments` (D: own id only) | ✓ | ✓ | | ✓ |
| `supplier:read` | ✓ | ✓ | ✓ | ✓ |
| `supplier:write` | ✓ | ✓ | | |
| `fuel:read` (D: own rows) | ✓ | ✓ | | ✓ |
| `fuel:write`, `fuel:receipt:upload` | ✓ | | | ✓ |
| `fuel:summary` | ✓ | ✓ | | |
| `trip:read` (D: own) | ✓ | ✓ | | ✓ |
| `trip:write` | ✓ | | | ✓ |
| `maintenance:read` | ✓ | ✓ | ✓ | |
| `maintenance:write`, `maintenance:mechanic-report` | ✓ | | ✓ | |
| `maintenance:upcoming`, `maintenance:overdue` | ✓ | ✓ | | |
| `compliance:read` (rules + status) | ✓ | ✓ | ✓ | |
| `compliance:write` (rules) | ✓ | ✓ | | |
| `inventory:read`, `po:read` | ✓ | ✓ | ✓ | |
| `inventory:write`, `po:write`, `po:receive` | ✓ | ✓ | | |
| `driver-report:read` (D: own) | ✓ | ✓ | | ✓ |
| `driver-report:write` | ✓ | | | ✓ |
| `incident:read` (D: own), `incident:create` | ✓ | ✓ | | ✓ |
| `incident:resolve` | ✓ | ✓ | | |
| `dashboard:read` | ✓ | ✓ | | |
| `document:read`, `document:search` (types scoped by role) | ✓ | ✓ | ✓ | ✓ |
| `document:upload`, `document:delete` | ✓ | ✓ | | |

Nav/route access (`nav:*`) is derived from this table, as in the nav mapping in
[00](00-design-analysis.md) §4. Also export `visibleDocumentTypes(role)` from the CLAUDE.md
§2.1 matrix.

## 10. Login page: `src/app/(auth)/login/page.tsx`

- Centered card on `--background` with the FleetOps mark and wordmark (`APP_NAME` from
  `src/lib/brand.ts`), styled with the reference's tokens.
- Fields: Organization (slug), Email, Password. Built with react-hook-form + zod
  (`org_slug` must match `^[a-z0-9-]+$`), validating on blur.
- Submit calls `POST /api/auth/login`. The button shows a pending spinner while it runs. A 401
  shows the form-level message "Invalid organization, email or password."; a 422 maps onto the
  fields. Success → `router.replace(next ?? "/dashboard")`, then invalidate `meKeys`.
- Has its own `loading.tsx` / `error.tsx`. Usable at 375px.

## 11. Tests (Vitest + MSW at the HTTP boundary)

| Target | Cases |
| --- | --- |
| `errors.ts` | Every status → kind; 422 with array vs string `detail`; network failure; 429 `retryAfter` |
| `client.ts` | Schema parse success and failure → `schema` error; 204; FormData content-type untouched; query serialization |
| `decimal.ts` | `"12.3400"` parsing, PKR formatting, null handling |
| BFF login route | Sets an httpOnly cookie and never returns the token; passes a 401 through |
| Proxy route | Attaches the bearer; 401 when there's no cookie; streams the body; rejects an absolute-URL path |
| `middleware.ts` | All four redirect cases + `next` sanitization (port the scaffold's tests: `git show 8424051:frontend/tests/middleware.test.ts`) |
| `rbac.ts` | **The full matrix**: every action × every role |
| `keys.ts` | Key stability and hierarchy (`detail(id)` starts with `all`) |
| Schemas | A fixture per response schema, taken from a real backend response |
| Login page | Validation, 401 message, 422 field mapping, redirect to `next` |

## 12. Exit criteria

- [x] Log in as each of the four seeded users, verified live against the seeded dev backend
      (`admin`, `fleet_manager`, `driver`, `mechanic`) — all return 200 with `{ok:true}`.
      `/auth/me` returns the correct `user`/`organization`/`driver_profile` shape for each
      (the seeded driver correctly shows `driver_profile: null`, per the README caveat).
- [x] The cookie is httpOnly (confirmed via the raw `Set-Cookie` header: `HttpOnly; SameSite=lax`);
      the response body never contains the token.
- [x] Deleting the cookie mid-session → the next query redirects: verified both via
      `/api/auth/logout` (clears the cookie; the next `/auth/me` call → 401) and via
      `middleware.ts` (an unauthenticated page request → 307 to `/login?next=…`, and the
      reverse: an authenticated request to `/login` → 307 to `/dashboard` or the sanitized
      `next`). An absolute-URL or `//host` `next=` is rejected (open-redirect check).
- [x] A 403 from an A/FM-only endpoint (`/dashboard/summary` as `driver`) passes through as
      `{kind: "forbidden", message: "Not enough permissions"}`, matching the backend exactly.
- [x] build, lint and tests (299, including the full rbac matrix and live-captured schema
      fixtures) all pass.
