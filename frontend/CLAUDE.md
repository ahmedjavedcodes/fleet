# CLAUDE.md — Frontend (FleetOps)

**Product name:** **FleetOps**, defined once as `APP_NAME` in `src/lib/brand.ts`. Never
hardcode the name elsewhere.

**Scope:** This file governs `frontend/` only: the Next.js dashboard that visualizes
the FastAPI backend (`backend/`) and the AI orchestration layer (`ai_agents/`). It
is the architectural contract for every frontend change. Where it conflicts with a
habit or a generic best practice, **this file wins**.

**Non-negotiables, before anything else:**

1. **Every screen reflects real backend behaviour.** Build against the endpoints listed
   in §5.4. Where a feature's API doesn't exist yet (§5.5), build the UI against a
   typed adapter with an explicit "not yet available" state. Never fake data in
   production code paths.
2. **No live telemetry.** This platform has no GPS, IoT or real-time tracking. All data
   comes from manual entry and uploaded files. Never design or label anything as
   "live location", "real-time tracking" or "vehicle position".
3. **The backend is the security boundary; the UI is courtesy.** Hiding a button for a
   role is UX. The backend's 403 is the enforcement, so every call must still handle
   one gracefully (§5.3).
4. **Pixel-perfect or it isn't done.** Every page ships with loading, empty, error and
   access-denied states that match the design system (§1, §6).

---

## 0. Tech Stack & Commands

| Concern | Choice | Notes |
| --- | --- | --- |
| Framework | **Next.js 15, App Router** (`src/app/`), React 19 | Server Components by default; `"use client"` only where interactivity requires it |
| Language | **TypeScript, `strict: true`** | No `any`, no `@ts-ignore`, no non-null `!` on API data |
| Styling | **Tailwind CSS v4** (`@tailwindcss/postcss`) | Tokens live in `src/app/globals.css` under `@theme` (§1.2) |
| Components | **shadcn/ui** (Radix primitives, copied into `src/components/ui/`) | Customize the copied source to match the design tokens; never wrap it in ad-hoc overrides |
| Server state | **TanStack Query v5** (`@tanstack/react-query`) | The only way components read or mutate backend data (§5) |
| Forms | `react-hook-form` + `zod` (+ `@hookform/resolvers`) | The zod schema is the single source of truth for form types |
| Charts | `recharts` | Styled only through design tokens |
| Icons | `lucide-react` | Never add a second icon library |
| Markdown (chat) | `react-markdown` + `remark-gfm`, **no `rehype-raw`** | LLM and document text is untrusted: never render raw HTML (§4.5) |
| Tests | Vitest + Testing Library (`vitest.config.mts`) | See §7 |

All installed (phase 01): `next`, `react`, `tailwindcss`, `zod`, `react-hook-form`,
`recharts`, `lucide-react`, Vitest, `@tanstack/react-query` (+ devtools),
`react-markdown`, `remark-gfm`, `msw` (dev), and shadcn/ui. shadcn was set up with:

```bash
npx shadcn@latest init -b radix -t next -p nova --no-monorepo --no-rtl -y
npx shadcn@latest add card badge dialog dropdown-menu sheet tabs table tooltip hover-card \
  skeleton sonner avatar separator scroll-area progress input label select textarea popover \
  alert-dialog breadcrumb toggle-group field -y
```

- **`cn`:** current shadcn imports `cn` from the `cn` package (shadcn's own replacement for
  `clsx` + `tailwind-merge`), also re-exported from `@/lib/utils`.
- **Forms:** use the `field` components, which replaced shadcn's older `form`.
- **Toasts:** `sonner` was customized to drop `next-themes` (there is no theme toggle).
- **After adding a component:** strip any arbitrary values (`ring-[3px]` → `ring-3`, etc.).
  `tests/app/globals.test.ts` fails the build on raw hex or arbitrary px/rem values in any
  `.tsx`.

| Script | Command |
| --- | --- |
| Dev server | `npm run dev` (http://localhost:3000) |
| Production build | `npm run build` — must pass with **zero** type or lint errors |
| Lint | `npm run lint` |
| Tests | `npm test` / `npm run test:watch` |

---

## 1. UI/UX Aesthetic & Design System

### 1.1 Inspiration references

**Never invent brand colors, gradients or shadows and present them as "the design".**
Values the reference doesn't show are marked *derived* in §1.2.

| # | Reference (Dribbble URL / image path) | What to take from it |
| --- | --- | --- |
| 1 | [`plans/assets/fleetyo-vehicle-detail.png`](plans/assets/fleetyo-vehicle-detail.png) | App shell (detached sidebar + topbar cards), grouped sidebar nav and its active state, sidebar user card, breadcrumbs, status pills, outline/icon action buttons, hero card, KPI tiles with colored icon squares, two-level panels (grey panel → white inner cards), area chart, warning callout, data table, health gauge |
| 2 | _TBD_ | Chat / AI surfaces (none in reference 1; build from reference 1's language until provided) |
| 3 | _TBD_ | Empty / error / access-denied illustrations |

The full analysis, including what in reference 1 **cannot** ship (live telemetry, fields
the backend doesn't have) and what replaces it, is in
[`plans/00-design-analysis.md`](plans/00-design-analysis.md). Reference 1's brand
("FleetYo") is not ours: the product is **FleetOps**.

Tokens were extracted **by measurement**: colors were pixel-sampled from the image.
Reference 1 is a photo of a monitor, so colors are approximate and the absolute pixel
scale is unknown. Radii and spacing keep the reference's *proportions* and are rounded
to the 4px grid. Every value in code must trace back to a row in §1.2.

### 1.2 Design tokens (single source of truth)

All visual values are CSS variables defined once in `src/app/globals.css` (Tailwind v4
`@theme` + shadcn's semantic variables), with a light and a dark set. Components use
**only** semantic utilities (`bg-card`, `text-muted-foreground`, `border-border`,
`rounded-lg`, `shadow-card`, …).

**Forbidden in components:** raw hex/rgb, arbitrary values (`bg-[#1a2b3c]`,
`p-[13px]`, `shadow-[...]`), inline `style={{}}` for design values.

**Light set** (measured from reference 1 unless marked *derived*). Contrast ratios are
WCAG 2.x, computed.

| Token group | Variable | Light value | Source / contrast |
| --- | --- | --- | --- |
| Brand | `--primary` | `#F5781E` | Measured (logo, nav icon). 2.77:1 on white, so **non-text only**: fills, icons, logo, active-nav icon. |
| | `--primary-strong` | `#B05616` | *Adjusted*: darkest-needed shade of `--primary` for AA text. 4.58:1 on `--primary-soft`, 5.0:1 under white text. Used for orange text, the default button bg and active-nav text. The reference's `#D16623` nav text (3.73:1) fails AA. |
| | `--primary-foreground` | `#FFFFFF` | White on `--primary-strong`: 5.01:1. |
| | `--primary-soft` | `#FFF2EE` | Measured (active nav bg). |
| | `--ring` | `#EA731D` | *Adjusted*: `--primary` darkened to 3.01:1 (the focus-indicator minimum). |
| Surfaces | `--background`, `--card`, `--popover`, `--sidebar` | `#FFFFFF` | Measured. The app is flat white; there is no background gradient. |
| | `--panel`, `--muted` | `#F7F7F7` | Measured (outer grey panel). |
| | `--table-head` | `#F5F5F5` | Measured (table header row). |
| Text | `--foreground` | `#111111` | Measured near-black (the photo crushes to `#000`–`#070707`). 18.9:1. |
| | `--muted-foreground` | `#5D5D5D` | Measured. 6.58:1 on white, 6.15:1 on `--panel`. The reference's `#D8D7D8` unit text (1.4:1) is **rejected**; units use this token. |
| Borders | `--border`, `--input` | `#ECECEC` | Measured. |
| Status | `--success` / `--success-strong` / `--success-soft` | `#36941A` / `#2F8117` / `#F0F8EF` | Measured, except `-strong`, which is *adjusted* for text: 4.53:1 on `-soft`. |
| | `--warning` / `--warning-strong` / `--warning-soft` / `--warning-border` / `--warning-icon` | `#F8AE0E` / `#A46038` / `#FFFBF3` / `#E5C597` / `#E1844D` | Measured, except `-strong` (*adjusted* for text, ≥4.5:1). Callout body text stays `--foreground`. |
| | `--info` / `--info-strong` / `--info-soft` | `#2987DB` / `#1F68A8` / `#EEF5FC` | Measured / *adjusted* for text (5.30:1 on `-soft`) / *derived*. |
| | `--destructive` / `--destructive-soft` | `#C8281E` / `#FDF0EF` | *Derived* (no red in the reference). 5.56:1 on white, 5.00:1 on `-soft`; white on `--destructive` 5.56:1. |
| Severity | `--sev-minor` / `--sev-moderate` / `--sev-severe` / `--sev-critical` | `--info` / `--warning` / `--primary` / `--destructive` | *Derived* from the palette; matches backend `IncidentSeverity`. **Always paired with a text label.** |
| KPI tiles | `--tile-green` / `--tile-blue` / `--tile-amber` / `--tile-purple` | `#21B52E` / `#2987DB` / `#F8AE0E` / `#8D1BFF` | Measured. The glyphs (`--tile-foreground`, `#FFFFFF` in both themes) are **decorative** (`aria-hidden`; the tile label carries the meaning), so no contrast minimum applies. Never put text on a tile color. |
| Charts | `--chart-1` … `--chart-5` | `#EA731D` orange, `#2987DB` blue, `#1FAC2C` green, `#C4890B` amber, `#8D1BFF` purple | Reference hues, each *adjusted* to ≥3:1 on `--card` (graphics minimum). |
| | `--chart-grid` | `#ECECEC` | `= --border`. |
| Gauge | `--gauge-start` / `--gauge-end` / `--gauge-track` | `#EBF3A8` / `#80D765` / `#EFEFEF` | Measured. Decorative arc; the score is also rendered as text. |
| Radius | `--radius` | `0.75rem` (12px) = `lg`: inner cards, rows, buttons, inputs | Proportions from the reference. Scale: `sm` 6px, `md` 10px (KPI icon tiles), `lg` 12px, `xl` 16px (outer cards and panels), `full` (pills). |
| Elevation | `--shadow-card` | `none` | Measured: the reference is flat, border-only. |
| | `--shadow-card-hover` | `0 1px 2px rgb(17 17 17 / 0.06)` | *Derived*. |
| | `--shadow-popover` | `0 8px 24px rgb(17 17 17 / 0.10)` | *Derived*: overlays need separation. |
| Typography | `--font-sans` | **Urbanist** (`next/font/google`) | Closest match to the reference's geometric sans. |
| | `--font-mono` | **JetBrains Mono** (`next/font/google`) | *Derived*: VINs and code. |
| | type scale | display 40/48 bold (plate) · h1 32/40 semibold (KPI values) · h2 20/28 semibold (panel titles) · h3 16/24 semibold · body 15/22 · caption 13/18 | Proportions from the reference. |
| Spacing | base unit | 4px grid | Page gutter 16px (≤ `md`), 20px above. Card padding 20px (inner) / 24px (outer). Gap between cards 16px. |
| Motion | `--ease-standard` | `cubic-bezier(0.2, 0, 0, 1)` | *Derived*. `--duration-hover` 150ms, `--duration-overlay` 200ms. Reduced motion → 0ms, and pulse/glow off. |

**Dark set** (*derived*: the reference is light-only). Same hue families, contrast
re-verified.

| Variable | Dark value | Contrast |
| --- | --- | --- |
| `--background` / `--sidebar` | `#0F0F10` | — |
| `--card` / `--popover` | `#17171A` | — |
| `--panel` / `--muted` / `--table-head` | `#1C1C20` | — |
| `--border` / `--input` | `#2F2F35` | — |
| `--foreground` | `#F2F2F2` | 15.98:1 on `--card` |
| `--muted-foreground` | `#A1A1AA` | 6.63:1 on `--panel` |
| `--primary` / `--ring` | `#F5781E` | 6.46:1 on `--card` (usable as text in dark) |
| `--primary-strong` | `#FB9A4F` | 8.38:1 on `--card` (orange text) |
| `--primary-foreground` | `#111111` | On the default button (`bg-primary-strong`): 8.85:1 |
| `--primary-soft` | `#2A1A10` | `--primary-strong` on it: 7.85:1 |
| `--success` / `--success-strong` / `--success-soft` | `#4ADE80` / `#4ADE80` / `#132016` | 9.67:1 on soft |
| `--warning` / `--warning-strong` / `--warning-soft` / `--warning-border` / `--warning-icon` | `#FBBF24` / `#FBBF24` / `#221A0A` / `#5C4410` / `#FB9A4F` | 10.31:1 on soft, 10.72:1 on `--card` |
| `--info` / `--info-strong` / `--info-soft` | `#60A5FA` / `#60A5FA` / `#131C2A` | 6.73:1 on soft, 7.04:1 on `--card` |
| `--destructive` / `--destructive-soft` | `#F87171` / `#2A1414` | 6.28:1 on soft, 6.47:1 on `--card`; `#111111` on it: 6.83:1 |
| `--chart-1` … `--chart-5` | `#F5781E`, `#60A5FA`, `#4ADE80`, `#FBBF24`, `#C084FC` | All ≥ 6.4:1 on `--card` |
| `--gauge-track` | `#2F2F35` | — |

Tile colors and the gauge gradient are unchanged in dark.

Dark mode is enabled by a `.dark` class on `<html>`. There is **no theme toggle yet**:
the reference has none, so the dark set exists so one can be added without a redesign.

### 1.3 Enterprise SaaS standards

- **Whitespace over dividers.** Group with spacing and card surfaces first; add borders
  only where the references do.
- **Every interactive element has four designed states:** default, hover, focus-visible
  (`--ring`) and disabled. Hover transitions use the motion tokens. Never remove focus
  outlines.
- **Data tables** (shadcn `Table`, or TanStack Table for sortable ones):
  - sticky header;
  - right-aligned numerics with tabular figures;
  - sort indicators;
  - row hover;
  - pagination or virtualization beyond 50 rows;
  - column headers that state units ("Cost (PKR)", "Odometer (km)").
- **Numbers:** format with `Intl.NumberFormat`. Currency comes from org settings, with
  PKR as the default: backend amounts are `Decimal` values serialized as strings, so
  parse them explicitly and never do float math on money. Dates use `Intl.DateTimeFormat`.
- **Severity and status** always pair color with a text label or icon; never color alone.
- **Accessibility:**
  - WCAG 2.2 AA contrast for every token pair;
  - full keyboard navigation;
  - `aria-live="polite"` for streaming AI text and toasts;
  - `prefers-reduced-motion` disables pulsing and glow animations.
- **Responsive:** desktop-first (fleet managers), but every page must be usable at 375px.
  Drivers log fuel from a phone. The sidebar collapses to a `Sheet` below `lg`.

---

## 2. Routing & Pages Structure

### 2.1 Route map

**Role key:** A = Admin, FM = Fleet Manager, M = Mechanic, D = Driver.

The access column is **derived from the backend's role gates** (`backend/app/api/*.py`),
not chosen by the frontend. If a role gets nothing on a page, hide its nav item for that
role **and** render the Access Denied state if the URL is opened directly.

| Route | Purpose | Visible to | Primary data (backend) |
| --- | --- | --- | --- |
| `/login` | Org slug + email + password | public | `POST /auth/login`, `GET /auth/me` |
| `/dashboard` | Fleet overview + quick stats | all (role-specific variant, §2.2) | A/FM: `GET /dashboard/summary`, `/fuel-trends`, `/maintenance-calendar`, `/fleet-health` |
| `/chat` | Full-screen Grand Orchestrator | all | `ai_agents/server.py` (port 8100, proxied via `api/proxy-agents`), §5.4 |
| `/foundation` | Redirects to `/foundation/vehicles` | all | — |
| `/foundation/vehicles` | Vehicle list, create/edit/delete | all (read); A/FM (write) | `/vehicles` |
| `/foundation/vehicles/[id]` | Vehicle detail (reference 1; region-by-role map in `plans/05`) | all (regions vary by role); assign/release A/FM | `/vehicles/{id}`, `/{id}/compliance`, `/{id}/assignments`, `/{id}/timeline`, `/fuel/summary`, `/fuel?vehicle_id`, `/trips?vehicle_id`, `/maintenance?vehicle_id`, `/incidents`, `/dashboard/fleet-health` (A/FM) |
| `/foundation/drivers` | Driver list, create/edit/delete | all (read); A/FM (write) | `/drivers` |
| `/foundation/drivers/[id]` | Driver detail: custody history, timeline | all (basic fields); timeline and assignments A/FM/D (D: own id only) | `/drivers/{id}`, `/drivers/{id}/assignments`, `/drivers/{id}/timeline` |
| `/foundation/suppliers` | Supplier list (no detail page: the backend has no GET-by-id) | all (read); A/FM (write) | `/suppliers` |
| `/fuel` | Fuel logs, consumption, cost/km, anomalies, trip logs | A, FM, D (write: A, D; summary: A, FM) | `/fuel`, `/fuel/summary`, `/fuel/{id}/receipt`, `/trips` |
| `/maintenance` | Service history, mechanic reports, inventory, POs, compliance | A, FM, M (log write: A, M; inventory/PO write: A, FM; upcoming/overdue: A, FM) | `/maintenance`, `/maintenance/{id}/mechanic-report`, `/maintenance/upcoming`, `/maintenance/overdue`, `/inventory`, `/inventory/low-stock`, `/purchase-orders`, `/compliance/status` |
| `/accountability` | Incidents, severity, shift reports, driver timelines | A, FM, D (resolve: A, FM; shift report write: A, D) | `/incidents`, `/driver-reports`, `/drivers/{id}/timeline` |
| `/assignment` | Vehicle ↔ driver custody: assign, release, history | A, FM (write + all history); D (own history, vehicle history) | `POST /vehicles/{id}/assign`, `/release`, `GET /drivers/{id}/assignments`, `/vehicles/{id}/assignments?target_date=` |
| `/insights` | Analytics and custom reporting | A, FM | Dashboard endpoints today; NL→SQL search **to be built** (§5.5) |
| `/documents` | RAG knowledge base: list, search, upload, manage | all (list/search, scoped by role); A/FM (upload/delete) | Documents API (**to be built**, §5.5 — lives only on the `backend` branch, never merged into `frontend`; see plan 07 §0) |
| `/notifications` | Tabs: Warnings, Notified Events (no Triggers tab — no rules engine in this release) | all | Notifications API |

All paths are under `${API_BASE}/api/v1`. Read-only helper: `GET /health`.

**Domain facts the UI must respect**, so pages don't promise what the backend doesn't do:

- **Assignment:**
  - Assignments are **custody records** (`assigned_at` / `released_at`), not future
    schedules. There is no roster or scheduling endpoint, so don't build a calendar
    scheduler.
  - Assignment is **vehicle-scoped**: there is no "list all assignments" endpoint, so
    history is fetched per vehicle or per driver.
- **Accountability:**
  - Incident **severity** is exactly `minor | moderate | severe | critical`.
  - Incidents are **immutable**; only resolution status and notes change.
  - Shift reports are **append-only**: a `PATCH`/`PUT` returns 405, so never render an
    edit action for them.
- **Fuel:** `cost_per_km` and `is_anomalous` are computed by the backend. Display them,
  **never** recompute them client-side.
- **Documents:** `document_type` is exactly
  `manual | policy | supplier_invoice | incident_report | legal`. The types each role
  can see come from the backend. The UI mirrors that matrix for filters but never relies
  on it for security.

  | Role | Visible document types |
  | --- | --- |
  | Admin | all five |
  | Fleet Manager | manual, policy, supplier_invoice, incident_report |
  | Mechanic | manual, policy |
  | Driver | manual, policy |

### 2.2 Role-specific dashboard

`/dashboard/*` endpoints are **Admin/Fleet-Manager only**. Never call them for other roles;
compose those dashboards from endpoints the role can actually read:

| Role | Dashboard composition |
| --- | --- |
| Admin / FM | Summary KPIs (vehicles, active drivers, month fuel cost, overdue maintenance, low-stock parts, open incidents) + fuel trend + maintenance calendar + fleet-health table |
| Mechanic | `GET /maintenance` (recent work), `GET /inventory/low-stock`, `GET /compliance/status` |
| Driver | Own fuel logs (`GET /fuel`), trips (`GET /trips`), incidents (`GET /incidents`), own timeline (`GET /drivers/{own driver id}/timeline`, the id comes from `/auth/me` `driver_profile`) |

### 2.3 File layout

```
src/
├── app/
│   ├── (auth)/login/page.tsx, loading.tsx, error.tsx
│   ├── (app)/                      # authenticated shell: sidebar + topbar (§3)
│   │   ├── layout.tsx
│   │   ├── dashboard/  chat/  fuel/  maintenance/
│   │   │     dashboard/_components/: Greeting, AdminDashboard, MechanicDashboard, DriverDashboard
│   │   ├── foundation/{vehicles,vehicles/[id],drivers,drivers/[id],suppliers}/
│   │   ├── accountability/  assignment/  insights/  documents/  notifications/
│   │   │     each: page.tsx, loading.tsx, error.tsx (+ _components/ for page-local UI)
│   ├── api/
│   │   ├── auth/login/route.ts     # BFF: sets the httpOnly session cookie; never returns the token
│   │   ├── auth/logout/route.ts    # BFF: clears the cookie (backend has no logout endpoint)
│   │   └── proxy/[...path]/route.ts  # attaches Bearer server-side; streams SSE/multipart through
│   ├── layout.tsx                  # <html>, fonts (Urbanist, JetBrains Mono), metadata, <Providers>
│   ├── providers.tsx               # "use client": QueryClientProvider, devtools (dev only), Toaster
│   └── globals.css                 # design tokens (§1.2) — the only CSS file
├── components/
│   ├── ui/                         # shadcn components (customized to tokens)
│   ├── primitives/                 # design-system building blocks (plans/00 §5): IconTile, SectionPanel,
│   │   │                           #   InnerCard, KpiTile, StatusPill, Breadcrumbs, InitialsAvatar, DataTable
│   ├── layout/                     # Sidebar, SidebarNav, MobileSidebar, Topbar, TopbarSlotsProvider,
│   │   │                           #   PageHeader, NotificationBell, UserMenu, RouteGuard, nav-items.ts
│   ├── states/                     # PageSkeleton (+ Skeleton* shape helpers), EmptyState, ErrorState,
│   │   │                           #   AccessDenied, QueryRegion, RouteErrorBoundary,
│   │   │                           #   RoutePlaceholder (see note below)
│   ├── charts/                     # AreaTrendChart (recharts, generic over series), HealthGauge (hand-rolled SVG semicircle)
│   ├── fleet/                      # DueRow, TimelineList, AssignDriverDialog/ReleaseDriverFlow (promoted here in plan 06
│   │   │                           #   once /assignment became a 2nd caller, per the _components/ promotion rule below)
│   ├── primitives/…, Callout       # warning-toned banner (fuel-anomaly / open-incident callout on vehicle detail, plan 05 §2.5)
│   └── ai/                         # chat-thread, message-bubble, composer, agent-panels (AgentActivity/
│       │                           #   ApprovalCard/HaltedCard), citation-pill (CitationPill/HoverCard/Sheet),
│       │                           #   document-library-table, document-upload-card — all built and unit-
│       │                           #   tested, none wired to a live page (plan 07 §0: `backend` — which has
│       │                           #   /documents, /memory and the chat orchestrator — is never merged into
│       │                           #   `frontend`; see CLAUDE.md's own note in §2.1/§5.5 below)
├── lib/
│   ├── brand.ts                    # APP_NAME = "FleetOps" — the only place the name lives
│   ├── utils.ts                    # cn() (shadcn)
│   ├── env.ts                      # zod-validated env, lazy (see note below)
│   ├── route-labels.ts             # pathname → sidebar label, for the topbar's fallback breadcrumb and
│   │                                #   AccessDenied's "area" text
│   ├── longest-prefix-match.ts     # shared by rbac.ts and route-labels.ts
│   ├── use-media-query.ts          # SSR-safe window.matchMedia hook (sidebar collapse — see note below)
│   ├── format-date.ts              # formatMonthLabel/formatDate/formatDateTime/formatDurationBetween (Intl, UTC-safe)
│   ├── enum-labels.ts              # backend enum value → display label + tone maps (service type, incident severity/type/…)
│   ├── health-score.ts             # healthScoreLabel(score): the Good/Fair/Poor UI-only threshold mapping (plan 05 §5)
│   ├── api/
│   │   ├── client.ts               # browser fetch → /api/proxy, zod-validates every response
│   │   ├── server-client.ts        # server-only twin: Server Component prefetch, talks to the backend directly
│   │   ├── errors.ts               # ApiError union + toApiError() — every page's ErrorState switches on `.kind`
│   │   ├── decimal.ts              # parseDecimal/formatMoney/formatNumber/formatInt (Decimal-string fields) plus
│   │   │                           #   formatMoneyValue/formatNumberValue for values a chart has already parsed to number
│   │   └── auth.ts, vehicles.ts, drivers.ts, fuel.ts, …  # one module per domain: plain functions + co-located hooks
│   ├── query/
│   │   ├── client.ts               # QueryClient factory (retry policy, 401 → redirect)
│   │   └── keys.ts                 # query-key factories, one per domain
│   ├── auth/
│   │   ├── session.ts              # server-only: cookie get/set/delete, getServerMe()
│   │   ├── token.ts                # server-only: getServerToken() (split out to avoid a session.ts ⇄ server-client.ts cycle)
│   │   ├── safe-next-path.ts       # shared by middleware.ts and the login page — open-redirect guard on ?next=
│   │   ├── use-current-user.ts     # "use client": the one source of the signed-in user/role/org
│   │   └── role-labels.ts          # UserRole → display label
│   ├── rbac.ts                     # route/action → roles matrix (mirrors §2.1), verified against require_role(...);
│   │                                #   also routeAllowedRoles() for AccessDenied's role-aware hint
│   └── schemas/                    # zod schemas mirroring backend Pydantic models; enums.ts, common.ts + one file/domain
└── middleware.ts                   # redirect unauthenticated users to /login

tests/                               # mirrors src/ path-for-path — see §7's Tests bullet
```

- `@/*` → `src/*`. Always import via `@/...`.
- Page-specific components live in `_components/` next to the page. Promote one to
  `src/components/` only once a second page needs it.
- **Hooks are co-located in the domain module** (`lib/api/vehicles.ts` exports both
  `listVehicles()`/`getVehicle()`/… and `useVehicles()`/`useVehicle()`/…), not split into a
  separate `lib/hooks/` tree — the whole domain lives in one file (plans/02 §7).
- **`lib/env.ts` validates lazily**, on first property access, not at module-import time.
  `next build` imports route handler modules to collect their metadata without any real env
  vars set; an eager `parse()` at import time would crash the build itself. Access still
  fails on the very first real request middleware ever sees.
- **`server-only`-guarded modules under test:** the `server-only` package's guard is a
  build-time export-condition trick Vitest doesn't implement, so it always throws under
  Vitest regardless of environment. `vitest.setup.mts` mocks it globally as a no-op — this
  is standard for testing Next.js server code and isn't something a unit test should
  re-verify (that guarantee is Next's bundler's job).
- **PageHeader's "portal" is a Context-based slot registry, not `ReactDOM.createPortal`**
  (`components/layout/topbar-slots.tsx`). A literal DOM portal into a
  `document.getElementById` target has real SSR-timing and duplicate-content hazards (the
  target doesn't exist during SSR, and the topbar has no clean way to know whether *any*
  page has portaled content yet, so it can render its pathname-derived fallback only when
  none has). `TopbarSlotsProvider` wraps both `<Topbar/>` and `{children}` in
  `(app)/layout.tsx`; `PageHeader` calls its setter in an effect and renders nothing
  itself. Same outcome as the plan's "portal" — a page's header lives next to its own data
  hooks, no prop-drilling through the layout — without those hazards.
- **Sidebar collapse is one JS boolean, not "CSS breakpoint for width + JS state for
  labels."** `Sidebar` derives `collapsed` from `useMediaQuery("(min-width: 1280px)")`
  combined with the manual toggle, and passes that single boolean to both the container's
  width class and `SidebarNav`/`UserMenu`'s children. Driving the width by a `xl:` Tailwind
  class while gating labels on a JS-only "manually collapsed" flag looked equivalent but
  wasn't: between `lg` and `xl` the container CSS-shrank to icon width while the JS state
  still said "expanded," so full label text tried to render inside an 80px column and
  overflowed. Caught by an actual browser screenshot at 1024px, not by the test suite.
- **`RoutePlaceholder`:** every route in §2.1 is scaffolded and kept
  in the nav now (all of CLAUDE.md §3's sidebar, filtered by role), rather than hidden
  until a later phase builds it. `RoutePlaceholder` ("… is being built") is currently
  unused — every scaffolded route has a real backend and a built UI (the former
  `NotAvailableYet` state has been removed). `/dashboard` (plan 04), `/foundation/*` (plan 05),
  `/fuel`, `/maintenance`, `/accountability`, `/assignment` (plan 06, reduced scope — see
  that plan's notes for what's deferred within each), `/insights` (plan 07, the analytics
  regions; its NL search box is presentational only) and `/chat` (plan 07, a real integration
  with `ai_agents/server.py`), `/documents` and `/notifications` are built and live.
- **Dashboard greeting is time-of-day, not literally "Good morning."** Plan 04 §1's copy
  ("Good morning, {first name}") was written before considering that a fleet manager
  checking in at 4pm shouldn't be told good morning; `_components/greeting.tsx` derives
  Good morning/afternoon/evening from `new Date().getHours()` instead. No CLAUDE.md
  conflict — the plan's literal string was never a contract, just placeholder copy.
- **`KpiTile` grew a `hint?: string` (tooltip) and a `"destructive"` tone** for the
  dashboard's "Open incidents" tile (plan 04 §2: counts open + investigating, so the
  tooltip disambiguates what the number includes). The tooltip trigger is `TooltipTrigger
  asChild` around a `<span role="button" tabIndex={0}>`, not a `<button>` — `KpiTile` can
  be wrapped in a `<Link>` (via `href`), and a `<button>` trigger there would nest
  interactive content inside an `<a>`, which is invalid HTML.

---

## 3. Global UI Layout & Navbar

The `(app)/layout.tsx` shell is persistent across every authenticated page and never
re-mounts on navigation.

- **Sidebar (primary navigation):**
  - Top: the FleetOps mark (truck in `--primary`) + wordmark (`APP_NAME`), and a
    `PanelLeft` collapse toggle.
  - One link per route in §2.1, **filtered by `lib/rbac.ts`** for the current role, each
    with a Lucide icon and label, grouped as in reference 1 (small muted group label, a
    divider between groups; a group with no visible items is hidden with its label):

    | Group | Items (route · icon) |
    | --- | --- |
    | Main Menu | Overview `/dashboard` · `LayoutGrid`; AI Assistant `/chat` · `Sparkles` |
    | Fleet | Vehicles `/foundation/vehicles` · `Truck`; Drivers `/foundation/drivers` · `Users`; Suppliers `/foundation/suppliers` · `Building2`; Assignment `/assignment` · `ArrowLeftRight` |
    | Operations | Fuel & Trips `/fuel` · `Fuel`; Maintenance `/maintenance` · `Wrench`; Accountability `/accountability` · `ShieldAlert` |
    | Knowledge | Documents `/documents` · `FileText` |
    | Insights | Insights `/insights` · `ChartColumn` |
    | Monitoring | Notifications `/notifications` · `Bell` |

    Reference 1's "Live Tracking", "Route", "Tasks", "Reports" and "Settings" items are
    **not** carried over (telemetry, or no such domain).
  - Active state comes from `usePathname()` (prefix match, so `/maintenance/...` still
    highlights Maintenance): `bg-primary-soft`, `text-primary-strong` label, icon in
    `text-primary`. Add `aria-current="page"` on the active link.
  - Bottom: a **user card** (initials avatar, full name, role label, `ChevronsUpDown`) that
    opens the user menu, as in reference 1.
  - Collapses to icon-only on `lg`, and to a `Sheet` drawer below it.
- **Topbar**, left to right: breadcrumbs, an optional page status pill, page actions
  (outline buttons with icon + label, then square icon-only buttons), then:
  - **Notification bell:** a Lucide `Bell` with an unread-count badge (hidden at 0,
    `99+` cap), opening a popover preview with a link to `/notifications`. Until the
    notifications API exists (§5.5) the bell renders with no badge. Never show a fake
    count.
  - **User menu:** a `DropdownMenu` opened from the sidebar user card, showing the user's
    **full name** and **role** badge (`Admin`, `Fleet Manager`, `Mechanic`, `Driver`),
    both read from the auth context (`GET /auth/me` → `user.full_name`, `user.role`,
    plus `organization.name`). Items: Sign out. (Add *Profile* only once a profile page
    exists; no dead UI.)
- **Never decode the JWT client-side** to get the name or role. It comes from `/auth/me`
  only.
- The shell owns the app-wide error boundary and the toast (`sonner`) container. Pages
  own their own `loading.tsx` / `error.tsx`.

---

## 4. Visualizing the AI (the "wow" factor)

**Implementation note (2026-09-29):** §4.1 below is the target design. The real first cut
(`app/(app)/chat/page.tsx`, `lib/api/chat.ts`, `ai_agents/server.py`) is simpler in three
ways, each because `OrchestratorSession.run/approve/modify/reject` are synchronous, blocking
calls with no token-level streaming inside the graph itself:
- **No conversation list / side panel.** `memory` is `None` on the server's `OrchestratorDeps`
  (no Pinecone dependency for a first pass), so there's no `memory_session_id` to list
  sessions by.
- **One coarse "Thinking…" activity step, not the real per-hop `FleetLiveObserver` trace.**
  Wiring the observer's actual UI events through to SSE is future work — currently the server
  emits a single synthetic `activity` event, not one per sub-agent hop.
- **Word-chunked "streaming," not real token streaming.** The full `final_response` comes
  back from one blocking call; the server splits it into words and sends each as a `token`
  event with a small delay, which animates like streaming but isn't token-level LLM output.

Everything else — HITL approvals never auto-approving, agent icon mapping, Stop via
`AbortController`, rendering activity/response text exactly as sent — is real and matches
this section.

### 4.1 Chat interface (`/chat`)

- **Layout:**
  - full-height thread with a sticky composer (multi-line; Enter sends, Shift+Enter adds
    a newline);
  - a conversation list, backed by agent-memory sessions (`memory_session_id`), in a
    collapsible side panel.
- **Streaming:**
  - Render tokens as they arrive over SSE (§5.5). Auto-scroll only while the user is at
    the bottom, and show a "Jump to latest" pill otherwise.
  - The assistant message container is `aria-live="polite"` and `aria-busy` while
    streaming.
  - A **Stop** button aborts the request (`AbortController`).
- **Agent activity (the core visual):**
  - While a turn runs, show a live activity rail built from the orchestrator's **UI
    events**. The backend already generates these as human-readable strings
    (`FleetLiveObserver.ui_messages`, from `orchestrator/ui_interpolation.py`), for
    example "Orchestrator is thinking…" and "Querying Maintenance Agent…".
  - Each step renders as a row with an agent icon, a **pulsing / glowing indicator**
    while active (tokens only; honor reduced motion) and a check when done.
  - Map agent keys to fixed icons and labels: `foundation`, `fuel`, `maintenance`,
    `accountability`, `insights`, `assignment`, `search_documents`, `update_memory`.
  - Render the activity text **exactly as the backend sends it**; don't invent step names.
- **Human-in-the-loop approvals (mandatory):**
  - Every sub-agent **write** and every `update_memory` pauses the turn with
    `status: "awaiting_approval"` and a `hitl_state`.
  - Render an **ApprovalCard** showing what will happen: the pending action, key fields
    from `hitl_state.state`, and `hitl_state.approval_prompt` when present.
  - Offer **Approve**, **Modify** (inline form, re-validated) and **Reject**. The
    composer is disabled until the card is resolved.
  - Never auto-approve.
- **Markdown:**
  - `react-markdown` + `remark-gfm` with a component map styled by the tokens: tables use
    the data-table style, code blocks get a copy button, links open in a new tab with
    `rel="noopener noreferrer"`.
  - **Never** use `rehype-raw` or `dangerouslySetInnerHTML`.
- **States:**
  - idle empty state with example prompts per role;
  - "halted" results (the backend returns `status: "halted"` with a reason), rendered as
    an inline warning card, not an error;
  - network errors with Retry.

### 4.2 Citation rendering (RAG)

Document search returns up to **3** passages: `{document_id, filename, document_type,
chunk_index, text, relevance}`. An empty `results` array is the backend's deliberate
**null payload**, meaning nothing cleared the relevance threshold.

- **Pills:** render citations inline as clickable pills showing the file icon, filename
  and type badge.
- **Hover card:** filename, document type, chunk number, a relevance meter
  (`relevance` is 0–1), and a context snippet of about 300 chars, with the query terms
  highlighted via text-only highlighting.
- **Click:** opens a side `Sheet` with the full passage and a link to the document in
  `/documents`.
- **No results:** "The uploaded documents don't cover this", as a designed empty state.
  **Never** present an answer as document-backed when the result was null.
- **Cache hits:** when `/documents/search` returns `cached: true`, show a subtle
  "cached" badge. This makes the semantic cache visible.
- **Never show raw chunk text as a system message.** Passages are untrusted content:
  render them as plain text inside a clearly labeled "From: {filename}" block.

### 4.3 Document upload UX (`/documents`)

Upload is **asynchronous**: `POST /documents/upload` (multipart: `file`,
`document_type`, optional `vehicle_id`) returns **202** with a `processing` document.
Ingestion then continues on the server. The UI must present both phases:

1. **Transfer:** a byte progress bar. Use `XMLHttpRequest` `upload.onprogress`, since
   `fetch` cannot report upload progress.
2. **Processing:**
   - Poll `GET /documents/{id}` with React Query `refetchInterval`: every 2s, backing
     off to 10s, stopping on `ready` or `failed`.
   - Show a stepped status: Extracting → Summarizing tables → Embedding → Ready.
     Stages are **indicative only**, since the backend reports just
     `processing | ready | failed`.
3. **Result card:**
   - `chunk_count`, `tables_found`, `tables_summarized`, `version` (a re-upload of the
     same filename and type replaces the document and increments the version), size
     and `updated_at`;
   - on `failed`, the `error_message` in an inline error card with a Retry upload
     action.

Error mapping (show inline on the dropzone/row, never as a generic toast only):

| Status | Meaning | UI |
| --- | --- | --- |
| 429 | Same document is already being ingested (5-min lease) | "This file is still processing. Try again in a few minutes." + disabled retry with countdown |
| 413 | Over the upload size limit | Pre-validate client-side; show limit |
| 415 | Not PDF / plain text | Pre-validate `accept=".pdf,.txt,.md"` + MIME |
| 422 | Empty file / invalid fields | Field-level errors |
| 404 | `vehicle_id` not in this org | Field error on vehicle picker |
| 403 | Role can't upload | Upload UI hidden for M/D; this is the fallback |
| 503 | Vector store unavailable | "Document processing is temporarily unavailable" + retry |

- **Upload and Delete controls:** render only for A/FM. Deleting uses a confirm dialog,
  and on success invalidates the list and search queries.
- **Search box:** calls `POST /documents/search` and renders results with the §4.2
  citation components.

### 4.4 Insights (`/insights`)

- **Today:** a rich analytics view built from the real dashboard endpoints, all A/FM:
  - fuel trend chart;
  - maintenance calendar;
  - fleet-health table with a per-signal breakdown (`compliance`, `incidents`,
    `maintenance_currency`, `fuel_efficiency`; any may be `null`, so render "n/a", never
    0).
- **Natural-language search box:** build it behind the typed adapter in §5.5. Until the
  NL→SQL endpoint exists, the box routes the question to `/chat`, or shows "coming
  soon". **Never** generate or run SQL in the browser.

### 4.5 AI security rules (UI side)

- Treat **all** model output and document text as untrusted: markdown without raw HTML,
  no `dangerouslySetInnerHTML`, no auto-following links, no auto-executed actions.
- Never place tokens, org IDs or document text in URLs or `localStorage`.
- The UI never builds prompts, never adds "system" text, and never strips the backend's
  `<untrusted_document_context>` framing.

---

## 5. State Management & API Integration

### 5.1 TanStack Query

- A single `QueryClient` is created per browser session in `<Providers>`. Defaults:
  `staleTime: 30_000`, `retry` that **never retries 4xx** (401/403/404/409/422/429) and
  retries network/5xx up to 2× with backoff, and `refetchOnWindowFocus: true` for list
  pages.
- **Query-key factories** live in `lib/query/keys.ts`, for example
  `vehicleKeys.all / .list(filters) / .detail(id)`. Never write inline string arrays in
  components.
- **Every mutation invalidates precisely:**
  - an assignment invalidates vehicle and driver histories plus the dashboard;
  - a fuel log invalidates fuel lists, fuel summary and dashboard trends;
  - a document upload or delete invalidates the documents list and all document-search
    queries.
- Optimistic updates are allowed only for idempotent, non-financial edits. Never for
  money, custody or incidents.
- Server Components may prefetch with `HydrationBoundary` for first paint. Client
  components still read through the same hooks.

### 5.2 API client & auth

- **Single entry point:** `lib/api/client.ts`. Components never call `fetch` directly;
  they call typed domain functions (`lib/api/fuel.ts` → `listFuelLogs()`), consumed via
  hooks (`useFuelLogs()`).
- **Every response is parsed with its zod schema** (`lib/schemas/*`, mirroring the
  backend Pydantic models) before it reaches UI code. A parse failure is a typed error
  surfaced via the error state, never silently ignored.
- **Auth (BFF pattern):**
  - `POST /api/auth/login` (Next route handler) calls the backend
    `POST /api/v1/auth/login` (`{org_slug, email, password}`) and stores the JWT in an
    **httpOnly, Secure, SameSite=Lax cookie**. Client JS never sees the token.
  - Browser calls go through `/api/proxy/[...path]`, which attaches
    `Authorization: Bearer` server-side and streams the response through. The proxy
    must also pass SSE and multipart uploads through.
  - `middleware.ts` redirects unauthenticated users to `/login`.
  - Session state comes from `GET /api/v1/auth/me`: `user`, `organization`,
    `driver_profile`.
- The backend embeds the org in the JWT, so there is **no org header** and no org id in
  requests.
- Never hardcode API URLs, tokens or IDs. Use `NEXT_PUBLIC_API_BASE_URL` (the public
  backend URL) and server-only env vars for the BFF.

### 5.3 Errors & RBAC degradation

A central error mapper in `lib/api/errors.ts` converts responses into a discriminated
union that every page's error state switches on:

| Status | Handling |
| --- | --- |
| 401 | Clear session → redirect to `/login?next=…` |
| **403** | **Never retry.** Page-level: render the designed **AccessDenied** state (icon, "You don't have access to {area}", role-aware hint, link back to dashboard). Action-level: disable the control with a tooltip explaining the required role |
| 404 | Designed not-found state within the page |
| 409 | Conflict (e.g. vehicle already assigned, stale summary): explain + offer refresh |
| 422 | Map Pydantic `detail[{loc,msg}]` onto form fields |
| 429 | Explain the wait (§4.3), no auto-retry storm |
| 503 | "Temporarily unavailable" + retry (vector store, document search) |
| 5xx / network | Error state + Retry; details to console only, never stack traces to users |

**Role-gated rendering:** `lib/rbac.ts` exports `can(role, action)`, mirroring §2.1.
Usage:

- Hide actions the role can't perform: Upload for M/D, Resolve incident for D, Assign
  for D/M.
- Hide nav items the role can't use.
- Still handle the 403 if the matrix drifts from the backend.

The backend is authoritative. If they disagree, the backend is right and `rbac.ts` gets
fixed.

### 5.4 Endpoint contract (exists today)

Build against these, with shapes from the backend schemas (`backend/app/schemas/*`):

- **auth:** `/auth/login`, `/auth/register`, `/auth/me`
- **foundation:** `/vehicles`, `/drivers`, `/suppliers`, plus timelines
- **fuel:** `/fuel`, `/fuel/summary`, `/fuel/{id}/receipt`, `/trips`
- **maintenance:** `/maintenance` (+ `/upcoming`, `/overdue`, `/{id}/mechanic-report`),
  `/inventory` (+ `/low-stock`), `/purchase-orders` (+ `/{id}/receive`),
  `/compliance/rules`, `/compliance/status`
- **accountability:** `/incidents`, `/driver-reports`
- **assignment:** `/vehicles/{id}/assign`, `/vehicles/{id}/release`,
  `/drivers/{id}/assignments`, `/vehicles/{id}/assignments`
- **dashboard:** `/dashboard/summary`, `/dashboard/fuel-trends`,
  `/dashboard/maintenance-calendar`, `/dashboard/fleet-health`
- **chat** (`ai_agents/server.py`, a separate process on port 8100, proxied through
  `api/proxy-agents` — not the main backend on 8000): `POST /api/v1/chat/sessions` (create),
  `POST /api/v1/chat/sessions/{id}/messages` → **SSE** (`activity`, `token`,
  `approval_required` with `hitl_state`, `done` with `status`, `error`), `POST …/approve`,
  `…/modify`, `…/reject`. Wraps `orchestrator.session.OrchestratorSession` directly — a real
  multi-agent run against the real backend, not a mock. See CLAUDE.md's own note on
  `ai_agents/server.py` and `frontend/plans/07-ai-surfaces.md` §0 for what's simplified
  (coarse-grained activity events, word-chunked "streaming" of an already-complete response
  rather than true token-level LLM streaming).

`/documents` and `/memory/sessions` are **not** in this list — they live only on the
`backend` branch (agents/memory/document-RAG), which is never merged into `frontend` (§5.5).

### 5.5 Contracts still to be built (build the UI, don't fake the data)

These features appear in this spec, but **no backend endpoint exists yet**. For each one:

- define the TypeScript contract in `lib/api/<feature>.ts`;
- implement a typed adapter that returns a `{ status: "unavailable" }` result;
- ship the UI with a designed "not available yet" state.

Wire the real endpoint the moment it lands. Never ship mock data behind a real-looking UI.

**`/chat` shipped 2026-09-29** — moved out of this table into §5.4 above. It's the one
exception to "no backend endpoint exists yet" in the frontend's *own* backend on 8000: its
server is `ai_agents/server.py`, a second, separate process on port 8100.

| Feature | Needed endpoint (proposed) | Backing today |
| --- | --- | --- |
| `/documents` | `GET /documents`, `POST /documents/upload`, `POST /documents/search`, `GET/DELETE /documents/{id}` | Exists only on the `backend` branch (agents/memory/document-RAG), which is **never merged into `frontend`** (plan 07 §0, decided 2026-09-29) — not "not yet built," but a standing decision not to bring it in |
| `/notifications` | `GET /api/v1/notifications?tab=warnings\|events\|triggers`, `PATCH …/{id}/read`, unread count | `AlertDispatcher` alerts (low stock, severe/critical incidents) are currently only logged. Tab mapping: **Warnings** = those alerts + overdue compliance; **Notified Events** = alerts already delivered; **Triggers** = the rule definitions that fire them |
| `/insights` NL search | `POST /api/v1/insights/query` → `{sql_preview?, columns, rows}` (read-only, safety-hook guarded) | `query_fleet_data` MCP tool is scaffolded but not wired to a read-only DB session |

---

## 6. UX Polish (every page, no exceptions)

Each route directory ships `page.tsx`, `loading.tsx` and `error.tsx`, and each data
region handles all five states:

| State | Requirement |
| --- | --- |
| Loading | **Skeletons shaped like the final content** (card grid, table rows, chart frame), never a lone spinner for page content. Spinners only inside buttons |
| Empty | Designed `EmptyState`: icon, one-line explanation, primary action if the role can act (e.g. "Log your first fuel entry"), none otherwise |
| Error | `ErrorState` with a human message from the §5.3 mapper + Retry (`reset()` / `refetch()`) |
| Access denied | `AccessDenied` (§5.3), never a blank page |
| Not available yet | For §5.5 features: honest, designed, no fake numbers |

- **Mutations:** the button enters a pending state (disabled + inline spinner), shows a
  success toast, and shows an inline error for 4xx. Destructive actions (delete,
  release, reject) require a confirm dialog.
- **Forms** validate on blur and submit with zod. Server 422s are mapped back onto
  fields, and field errors are announced to screen readers.
- **Perceived performance:** prefetch on nav hover, keep previous data while refetching
  (`placeholderData: keepPreviousData`), and never block the shell on a page query.

---

## 7. Coding Standards

- **Types:**
  - zod schema → `z.infer` type. **Never** hand-write a type that duplicates a schema.
  - Backend enums (`UserRole`, `IncidentSeverity`, `DocumentType`, `DocumentStatus`,
    `ServiceType`, `VehicleCondition`, …) are string-literal unions mirroring
    `backend/app/models/enums.py` exactly.
- **Numbers:** `Decimal` fields arrive as strings; convert with a single helper. IDs are
  UUID strings.
- **Components:** Server Components by default. `"use client"` only for interactivity,
  hooks or browser APIs. No data fetching in `useEffect`; use React Query.
- **Size limits:** keep a component under about 200 lines and extract subcomponents.
  One exported component per file, in PascalCase. Hooks are `useX`.
- **No dead UI:** no placeholder buttons that do nothing, no lorem ipsum in committed
  code, no commented-out JSX.
- **Tests** (Vitest + Testing Library):
  - Live under `tests/`, mirroring `src/`'s structure path-for-path (e.g.
    `src/lib/rbac.ts` → `tests/lib/rbac.test.ts`; `src/app/(auth)/login/page.tsx` →
    `tests/app/(auth)/login/page.test.tsx`), not co-located with the source file. Import
    the module under test via `@/...`, never a relative `./...` (that only resolved to a
    sibling when the test lived next to it).
  - every `lib/api` function (schema parsing, error mapping incl. 403/429);
  - `rbac.ts` (the full matrix);
  - query-key factories;
  - key components in all five §6 states: `ApprovalCard`, `CitationPill`, the upload
    flow including a 429, `AccessDenied`.
  - Mock at the HTTP boundary (MSW or a fetch mock), never inside components.
- **Done means:**
  - `npm run build`, `npm run lint` and `npm test` all pass;
  - the page was checked in a real browser at 375px and 1440px, for every role that can
    see it;
  - the loading, empty, error and denied states were all verified.

---

## 8. Keeping This File True

- If the backend adds, removes or re-gates an endpoint, update §2.1, §5.4 and `rbac.ts`
  in the same change.
- When a §5.5 endpoint ships, move it to §5.4 and delete its "not available yet" path.
- When design references land, fill in §1.1 and §1.2 before building further UI.
