# 04 — Dashboard (`/dashboard`)

**Goal:** a role-specific overview in the reference's visual language (KPI tiles, section
panels, area chart, health gauge), built only from endpoints each role can read (CLAUDE.md
§2.2).

**Depends on:** 03. **Shares components with:** 05 (`AreaTrendChart`, `HealthGauge`, `DueRow`).

---

## 1. Variant selection

`page.tsx` reads the role from `useCurrentUser()` and renders one of `AdminDashboard`,
`MechanicDashboard` or `DriverDashboard` (`_components/`). **Never call `/dashboard/*` for M or
D**; those endpoints 403 for them.

Header: breadcrumbs `Overview`. The page title is "Good morning, {first name}" (from
`/auth/me`), with `organization.name` muted underneath. Page actions per role: see below.

## 2. Admin / Fleet Manager

```
┌ KPI tiles (6, responsive grid 3×2 → 2×3 → 1×6) ─────────────────────────────┐
│ Vehicles · Active drivers · Fuel cost (month) · Overdue maintenance ·        │
│ Low-stock parts · Open incidents                                             │
├ Fuel cost trend (SectionPanel, 2/3 width) ─────┬ Upcoming & overdue (1/3) ──┤
│ AreaTrendChart, 6/12/24-month toggle           │ DueRow list                 │
├ Fleet health (SectionPanel, full width) ───────┴─────────────────────────────┤
│ DataTable: plate · health (mini gauge + score) · 4 signal columns · link    │
└──────────────────────────────────────────────────────────────────────────────┘
```

| Region | Endpoint | Rendering |
| --- | --- | --- |
| KPI tiles | `GET /dashboard/summary` | `KpiTile`s using the reference's tile colors: vehicles (blue, `Truck`), active drivers (purple, `Users`), fuel cost month (green, `Fuel`, PKR from `month_fuel_cost`), overdue maintenance (amber, `Wrench`), low-stock parts (amber, `PackageMinus`), open incidents (destructive, `ShieldAlert`; counts open + investigating, so say "Open & investigating" in the tooltip). Each tile links to its module page. A zero is shown as "0", not hidden. |
| Fuel trend | `GET /dashboard/fuel-trends?months=6\|12\|24` | `AreaTrendChart`: x = month (`MMM yy`), y = `total_cost` (PKR). A second series, `avg_cost_per_km`, goes on a secondary axis in `--chart-2`, **only if** it has non-null values. The backend fills in months with no data, so gaps are real zeros; `null` `avg_cost_per_km` breaks the line (no interpolation). The range toggle is a `ToggleGroup` in the panel header (the reference's "Last 30 days" select position). |
| Upcoming & overdue | `GET /dashboard/maintenance-calendar?window_days=30` | `DueRow`s sorted overdue-first: service type icon + label, plate, right-aligned "Due at {due_km} km" or "Due {date}" / "Overdue". The calendar items carry no current odometer, so don't compute "km remaining" here. `due_date` may be null for km-only items. Status pill: `warning` for upcoming, `destructive` for overdue. "View all" → `/maintenance`. |
| Fleet health | `GET /dashboard/fleet-health` | `DataTable` sorted by score ascending (worst first). The score cell is a mini `HealthGauge` + number + label (Good / Fair / Poor, see 05 §5). Signal columns: Compliance, Incidents, Maintenance, Fuel efficiency, each a number or **"n/a" for null (never 0)**. The row links to `/foundation/vehicles/{id}`. Retired vehicles are excluded by the backend, so the footnote says so. |

**Page actions (A/FM):** "Add vehicle" → `/foundation/vehicles?new=1`. No "Assign task"
equivalent here.

**Queries:** the four regions are independent `QueryRegion`s, so a slow fleet-health request
doesn't block the KPIs. Server-side prefetch covers `summary` only, for first paint.

## 3. Mechanic

| Region | Endpoint | Rendering |
| --- | --- | --- |
| Recent work | `GET /maintenance` (the newest 10 by `date`, sorted client-side since there's no pagination) | `TimelineList` (reference style): date, service type, plate (resolved via `GET /vehicles`, cached), cost, and a "has mechanic report" badge. |
| Low stock | `GET /inventory/low-stock` | `DataTable`: part, on hand, reorder level, **deficit** (backend field). |
| Compliance | `GET /compliance/status` | Per vehicle: counts of `overdue` / `due_soon`, then the worst items as `DueRow`s. |

**Page actions (M):** "Log service" → the `/maintenance` create form.

## 4. Driver

The driver's `driver_profile` comes from `/auth/me`.

- **`driver_profile === null`** (for example the seeded driver): the whole page is a designed
  `EmptyState` saying "Your account isn't linked to a driver profile yet. Ask your fleet
  manager to link it." No data calls are made, since they'd return empty lists, and
  `POST /fuel` would 422.
- With a profile:

| Region | Endpoint | Rendering |
| --- | --- | --- |
| Current vehicle | `GET /drivers/{own id}/assignments` → `current_assignment` | A hero-style card: plate, make/model, since `assigned_at`, `start_odometer`. When there's none: "No vehicle assigned." |
| My fuel logs | `GET /fuel?limit=5` (the backend scopes it to own rows) | Rows: date, liters, total (PKR), `cost_per_km` as-is, and an **anomaly badge** when `is_anomalous`. |
| My trips | `GET /trips` (own) | The last 5: date, distance (km), duration. |
| My incidents | `GET /incidents` (own) | Severity pill + status. |
| My timeline | `GET /drivers/{own id}/timeline` | `TimelineList` of trips, reports and incidents. |

**Page actions (D):** "Log fuel" and "Log trip" (both allowed for D), each opening the
create form from plan 06. Mobile-first layout: at 375px the actions sit in a sticky bottom
bar, since drivers log fuel from a phone.

## 5. Components introduced here (shared with 05)

- **`AreaTrendChart`** (`src/components/charts/area-trend-chart.tsx`):
  - recharts `AreaChart` with a `linearGradient` fill from `--chart-1` to transparent, and
    dot markers;
  - dashed `--chart-grid` gridlines, axis text in `--muted-foreground`;
  - a tooltip card styled like the reference's "Braking Events" chip;
  - optional `annotations` (used by 05 for anomaly days);
  - reads colors from CSS variables, with no hex.
- **`HealthGauge`** (`src/components/charts/health-gauge.tsx`):
  - an SVG semicircle with a `--gauge-track` background arc and a gradient value arc
    (`--gauge-start` → `--gauge-end`), plus the center score, "/100" and label;
  - a `size` prop (`sm` for the table, `lg` for 05);
  - `role="meter"` with `aria-valuenow`, `aria-valuemin`, `aria-valuemax`, `aria-valuetext`;
  - accepts `score: number | null`: null renders "n/a" with an empty arc.
- **`DueRow`** (`src/components/fleet/due-row.tsx`).

## 6. Tests

- Variant selection: every role gets the right variant; M/D never request `/dashboard/*`
  (assert with MSW: an unexpected-request handler fails the test).
- Admin: the KPI tiles format PKR from a decimal string; null signals render "n/a"; a 403 on
  summary → `AccessDenied` in that region only.
- Driver: the `driver_profile: null` empty state; an anomaly badge appears when
  `is_anomalous`.
- `AreaTrendChart` with null points; `HealthGauge` with 0, 76, 100 and null.
- Every region in loading, empty, error and denied states.

## 7. Exit criteria

- [x] With seed data created (vehicles, drivers, fuel logs, maintenance logs, trips and an
      incident, via the running backend's `POST` endpoints), each of the four seeded roles
      (admin, fleet_manager, mechanic, driver) was logged into headless Chrome via raw CDP and
      the dashboard rendered real numbers end to end: KPI tiles, the fuel-trend area chart, the
      fleet-health table with gauges, the mechanic's recent-work timeline, and the driver's
      current vehicle / fuel logs / trips / incidents / timeline. Regions with genuinely no rows
      in the live org rendered their designed empty state ("Nothing due", "Stock is healthy",
      "No compliance rules yet"); the `driver_profile === null` empty state is covered by
      `tests/app/(app)/dashboard/_components/driver-dashboard.test.tsx` (asserts zero data hook
      calls). This surfaced and fixed a real bug: `GET /drivers/{id}/timeline`'s `summary`
      object (built via raw SQL `jsonb_build_object` in `backend/app/services/timeline_service.py`)
      serialized `fuel_consumed`/`estimated_cost` as JSON numbers instead of the Decimal-as-string
      convention every other endpoint follows, failing the frontend's Zod schema. Fixed with an
      explicit `::text` cast in the SQL, plus a regression test
      (`test_timeline_summary_decimal_fields_serialize_as_strings`).
- [x] Visual check against the reference at 1440px (tiles, panels, chart style) and 375px, for
      all four roles, via CDP screenshots. Responsive layout (sidebar → hamburger, KPI grid →
      single column) holds up; the topbar's breadcrumb truncates under the driver's two page
      actions at 375px, which is existing phase-03 `shrink-0` action / `min-w-0` breadcrumb
      behavior, not a regression.
- [x] build, lint and tests pass (453 tests, `npm run lint`, `npx tsc --noEmit`, `npm run build`
      all clean).
