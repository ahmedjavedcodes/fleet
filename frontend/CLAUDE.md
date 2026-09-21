# CLAUDE.md — Frontend (Fleet Management SaaS)

**Scope:** This file governs the `frontend/` Next.js application only. It inherits the global constraints from the repository root `CLAUDE.md` (no real-time hardware/IoT/GPS — all data comes from manual entry and uploaded files) and translates them into frontend-specific rules.

---

## 1. Tech Stack & Build Commands

- **Framework:** Next.js 15 (App Router, `src/app/`), React 19, TypeScript (strict mode).
- **Styling:** Tailwind CSS v4 (via `@tailwindcss/postcss`).
- **Icons:** `lucide-react` — do not add a second icon library.
- **Charts:** `recharts` — used for fleet analytics, fuel trends, and executive insights visualizations.
- **Backend target:** FastAPI, versioned API at `http://localhost:8000/api/v1` (see [API Integration](#3-api--authentication-integration)).
- **Path alias:** `@/*` maps to `src/*` (`tsconfig.json`). Always import via `@/...`, never deep relative paths (`../../../lib/...`).

### Scripts

```bash
npm run dev         # Start local dev server (http://localhost:3000)
npm run build       # Production build
npm run start       # Serve production build
npm run lint        # ESLint (eslint-config-next)
npm run test        # Vitest — single run
npm run test:watch  # Vitest — watch mode
```

Run `npm run lint`, `npm run test`, and ensure `npm run build` succeeds before considering a feature complete — Next.js surfaces type errors and invalid Server/Client Component boundaries at build time.

### Testing

- **Stack:** Vitest + `@testing-library/react` (`jsdom` environment). Config: `vitest.config.mts` / `vitest.setup.mts` at the repo root (`.mts`, not `.ts`, so Vite's native ESM config loader doesn't warn — don't rename back to `.ts`).
- **Convention:** all tests live under `tests/`, mirroring the `src/` path of the file they cover (`src/lib/api-client.ts` → `tests/lib/api-client.test.ts`, `src/app/login/page.tsx` → `tests/app/login/page.test.tsx`). Don't co-locate a `*.test.ts(x)` next to its source file. Since a test file is no longer next to its source, import the subject via the `@/` alias (`import { apiFetch } from "@/lib/api-client"`), never a relative path back into `src/`.
- **What to test:**
  - Pure logic (Zod schemas, `api-client.ts`'s status→`ApiError.kind` mapping, `middleware.ts`'s redirect rules) gets full-coverage unit tests — cheap, no DOM needed.
  - Client Components that hold real logic (form validation, error-to-field mapping) get a behavioral RTL test; a component that's pure layout (e.g. `Skeleton`) doesn't need one beyond a smoke render.
  - Server Components (e.g. `dashboard/page.tsx`) aren't directly unit-testable with RTL — cover the data-shaping logic they call, and rely on `npm run build` + manual verification for the rendering itself.
- **Mocking `useAuth`/`next/navigation`:** a Client Component under test should `vi.mock("@/lib/auth-context")` and mock `next/navigation`'s hooks rather than rendering a real `AuthProvider` — that keeps the test isolated to the component's own logic instead of exercising the whole auth stack. See `tests/app/login/page.test.tsx` for the pattern.
- Vitest's globals (`describe`/`it`/`expect`) are **not** enabled — import them explicitly from `"vitest"` in every test file. RTL's auto-cleanup is wired manually in `vitest.setup.mts` (`afterEach(cleanup)`) because of this — don't remove it, tests will bleed DOM state across cases without it.

---

## 2. Directory Structure & App Router Architecture

```text
frontend/
├── src/
│   ├── app/                     # App Router — one folder per route segment
│   │   ├── layout.tsx           # Root layout (fonts, providers, global nav)
│   │   ├── page.tsx             # Landing / redirect to dashboard
│   │   ├── dashboard/           # Spec 05 — Executive Fleet Insights
│   │   ├── registry/            # Spec 00 — Entity management + Fleet Registry Agent UI
│   │   ├── fuel/                # Spec 01 — Fuel logs & leakage auditor
│   │   ├── maintenance/         # Spec 02/03 — Maintenance logs & parts inventory
│   │   ├── incidents/           # Spec 04 — Incident reports & driver timelines
│   │   └── copilot/             # Multi-agent chat workspace (image upload, multi-turn)
│   ├── components/              # Shared UI components (tables, dropzones, chat drawer, charts)
│   │   └── ui/                  # Low-level primitives (buttons, inputs, skeletons, banners)
│   └── lib/
│       ├── api-client.ts        # Central fetch wrapper — all HTTP calls go through this
│       ├── auth.ts              # Token storage/retrieval helpers (never inline in components)
│       ├── schemas/             # Zod schemas mirroring backend Pydantic models
│       └── types/               # TypeScript interfaces mirroring backend Pydantic models
├── .env.example
└── next.config.ts
```

### Route ↔ Spec mapping

| Route          | Purpose                                             | Spec |
|----------------|------------------------------------------------------|------|
| `/dashboard`   | Executive Fleet Insights                              | 05   |
| `/registry`    | Entity management & Fleet Registry Agent UI           | 00   |
| `/fuel`        | Fuel logs & leakage auditor                           | 01   |
| `/maintenance` | Maintenance logs & parts inventory                    | 02/03|
| `/incidents`   | Incident reports & driver timelines                   | 04   |
| `/copilot`     | Multi-agent chat workspace (image upload, multi-turn) | —    |

### Server vs. Client Components

- Default to **Server Components** for data fetching (route `page.tsx` files, list/detail views). Fetch directly in the component using `lib/api-client.ts`; do not wrap simple server-side reads in `useEffect`.
- Use `"use client"` only where interactivity is required:
  - `/copilot` chat interface (streaming responses, message state, image upload previews).
  - Forms with client-side validation (log entry, incident reports, registry entity forms).
  - Any component using hooks (`useState`, `useEffect`, Recharts interactive tooltips) or browser-only APIs.
- Keep client components as small and low as possible in the tree ("leaf" client components) — do not mark an entire page `"use client"` just because one child needs interactivity.

---

## 3. API & Authentication Integration

- **Base URL:** `NEXT_PUBLIC_API_BASE_URL` (see `.env.example`, defaults to `http://localhost:8000`). All backend calls target the versioned API — build paths as `` `${NEXT_PUBLIC_API_BASE_URL}/api/v1/...` `` rather than hardcoding `/api/v1` inline in components.
- **Single entry point:** All HTTP calls go through `src/lib/api-client.ts`. Do not call `fetch()` directly from components or pages — extend the client instead (e.g., add typed wrapper functions per resource: `getVehicles()`, `createIncident()`).
- **Auth headers:** Every authenticated request must attach `Authorization: Bearer <token>` — token read from the auth helper in `lib/auth.ts`, never read from `localStorage`/cookies inline in a component. There is no separate organization header: the backend embeds `organization_id` inside the JWT itself (`decode_access_token` reads the `org` claim), so multi-tenant scoping is automatic once the token is attached.
- **Login shape:** `POST /api/v1/auth/login` takes `{ org_slug, email, password }` (email is unique per-organization, not globally) and returns `{ access_token, token_type, expires_in }`. `POST /api/v1/auth/register` creates an organization + its first admin user in one call. `GET /api/v1/auth/me` returns the current user/organization/driver-profile — use it to hydrate session state on load, never decode the JWT client-side to read user data.
- **Never hardcode JWTs, org IDs, or API keys** anywhere in source, tests, or comments. Use environment variables or values from the authenticated session only.
- **Multipart uploads:** For image uploads (Fleet Registry Agent document capture, Copilot vision input, incident photos), send `multipart/form-data` and:
  - Do **not** manually set the `Content-Type` header — let the browser set the multipart boundary.
  - Restrict file inputs to `.jpg`/`.jpeg`/`.png` via the `accept` attribute and re-validate MIME type client-side before upload.
  - Enforce a max file size client-side (confirm the limit against backend config) and show a clear inline error if exceeded.
- **HTTP error handling** — the API client (or a shared error-handling utility it calls) must distinguish:
  - `401` → clear local session state and redirect to login.
  - `403` → show a permission-denied message; do not retry.
  - `409` → surface a conflict message (e.g., duplicate entity, stale data) and offer refresh/retry; do not silently overwrite.
  - `422` → map field-level validation errors back onto the form (Pydantic error shape: `detail: [{loc, msg, type}]`).
  - `500` / network failure → generic error banner + retry action; log details for debugging, never expose stack traces to the user.

---

## 4. Output Validation, Error Handling & UX Polish

### Schema guards

- Every form and every API response boundary must be validated with **Zod**, with schemas kept in `src/lib/schemas/` and named to mirror the backend Pydantic model (e.g., `VehicleCreateSchema` ↔ backend `VehicleCreate`).
- Use **React Hook Form** (`useForm` + `zodResolver`) for all multi-field forms (registry entities, log entry, incident reports). Do not hand-roll form state with ad hoc `useState` for anything beyond a single input.
- When a backend Pydantic schema changes, update the corresponding Zod schema and TypeScript interface in the same PR — they must never drift.

### Retry logic & fallbacks

- Wrap network calls that can transiently fail (agent vision extraction, PDF/CSV parsing jobs) with **exponential backoff** (e.g., 3 attempts, base delay 500ms, doubling), not a fixed-interval retry.
- If an agent operation (vision extraction, document parsing) times out or fails after retries, **degrade gracefully**: let the user proceed with manual entry instead of blocking the flow. Never leave the UI in an indefinite spinner state — always cap wait time and surface a fallback action.

### UI state machine

Every data-driven view must explicitly handle, and visibly differentiate:

- **Loading:** skeleton components (matching the shape of the eventual content) for initial loads; inline spinners for in-place actions (submit, refresh).
- **Error:** a dismissible banner for page/section-level failures; inline field errors for validation failures (from Zod or mapped `422` responses).
- **Empty:** a dedicated empty state per data table/list (e.g., "No fuel logs yet — add your first entry") — never render a bare empty table or blank div.
- **Success:** transient confirmation (toast) for mutations (create/update/delete) rather than a full page reload.

Do not conflate these states — a component should not be able to render "loading" and "error" simultaneously, and empty vs. loading must be visually distinct.

---

## 5. Strict AI Rules

1. **Never hardcode JWTs, secrets, or org identifiers.** Pull them from the auth/session layer or environment variables only.
2. **Keep TypeScript interfaces and Zod schemas synchronized with backend Pydantic models.** If you change one side, update the other in the same change.
3. **Server Components by default; `"use client"` only for interactivity** (agent chat, forms with client-side validation/state, anything using hooks or browser APIs).
4. **No live telemetry assumptions.** Every data view is fed by uploaded files (CSV/PDF/images) or manual form entry — do not design components around polling live GPS/IoT feeds or real-time device state.
5. **Route all HTTP traffic through `src/lib/api-client.ts`.** No direct `fetch()`/`axios` calls scattered in components.
6. **Every new feature ships with its Loading/Error/Empty states and Zod validation** — a form or data view without these is incomplete, not a follow-up task.
7. **Do not introduce a second icon library, chart library, or form library** beyond `lucide-react`, `recharts`, and React Hook Form + Zod without discussing it first — consistency across the dashboard matters more than a marginally better fit for one screen.
