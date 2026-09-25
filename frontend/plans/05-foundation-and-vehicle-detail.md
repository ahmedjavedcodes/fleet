# 05 — Foundation & Vehicle Detail

**Goal:** the Foundation area (vehicles, drivers, suppliers) with the **vehicle detail page as
the pixel-level implementation of the reference**
([assets/fleetyo-vehicle-detail.png](assets/fleetyo-vehicle-detail.png)). Every region of
the reference is mapped to a real endpoint, or deliberately replaced, per
[00](00-design-analysis.md) §3.

**Depends on:** 03 (and 04's `AreaTrendChart` / `HealthGauge` / `DueRow`; whichever of 04 and
05 lands first builds them).

**Routes** (recorded in CLAUDE.md §2.1 by plan 01):

| Route | Content | Visible to |
| --- | --- | --- |
| `/foundation` | Redirects to `/foundation/vehicles` | all |
| `/foundation/vehicles` | Vehicle list | all (write: A/FM) |
| `/foundation/vehicles/[id]` | **Vehicle detail (the reference)** | all, regions vary by role |
| `/foundation/drivers`, `/foundation/drivers/[id]` | Driver list and detail | all (write: A/FM) |
| `/foundation/suppliers` | Supplier list | all (write: A/FM) |

---

## 1. Vehicle list: `/foundation/vehicles`

- **Header:** crumbs `Fleet / Vehicles`. Action "Add vehicle" (A/FM) opens a `Dialog` form;
  `?new=1` opens it on load (linked from the dashboard).
- **`DataTable`** from `GET /vehicles`:
  - columns: Plate (bold, links to the detail page), Make & model, Year, Fuel type,
    Status (`StatusPill`), Odometer (km, right-aligned, tabular);
  - client-side sort and search (plate/make/model), a status filter, and pagination beyond
    50 rows;
  - a row `…` menu (A/FM): Edit, Delete (confirm dialog; the backend soft-deletes).
- **Form:** react-hook-form + zod mirroring `VehicleCreate` / `VehicleUpdate`: plate, make,
  model, year, VIN, fuel type, status, current odometer, service interval km/months.
  A 422 maps onto fields; a 409 (duplicate plate/VIN) becomes a field error.
- **Empty:** "No vehicles yet". "Add your first vehicle" for A/FM; nothing for M/D.

## 2. Vehicle detail: `/foundation/vehicles/[id]`, region map

Layout at 1440px mirrors the reference:

```
┌ Hero card (≈ 2/3) ───────────────────────────────┬ KPI tiles 2×2 (≈ 1/3) ──────┐
├ Maintenance panel ──┬ Trip performance panel ────┬ Health panel ───────────────┤
└─────────────────────┴────────────────────────────┴─────────────────────────────┘
```

- **< `xl`:** hero full width, tiles 2×2 below it, then the panels in 2 columns.
- **< `md`:** everything in 1 column, in this order: hero, tiles, trip, maintenance, health.

### 2.1 Topbar (via `PageHeader`)

| Reference | Implementation |
| --- | --- |
| Crumbs `Fleet / Vehicles / AB 1234 CJ - Foton Auman 2016` | `Fleet / Vehicles / {plate_number} — {make} {model} {year}` |
| "On Route · Surabaya → Malang" pill | `StatusPill` from `vehicle.status`: `active` → success "Active", `maintenance` → warning "In maintenance", `retired` → neutral "Retired" |
| "Contact Driver" | Outline `ActionButton` (`Phone`), a `tel:` link to the assigned driver's phone. Rendered only when there is an active assignment with a phone and the role can read assignments (A/FM/D). |
| "Assign Task" | **"Assign driver"** (no active assignment) or **"Release driver"** (active). A/FM only. See 2.7. |
| Flag icon button | **Report incident** (`Flag`, tooltip). A/FM/D. Opens the incident create form from plan 06, prefilled with `vehicle_id`. |
| Share icon button | **Copy link** (`Share2`). Copies `location.href` and shows a toast. |

### 2.2 Hero card

| Reference | Source | Notes |
| --- | --- | --- |
| Truck photo | None, since there's no photo field | `--panel` rounded tile with a large Lucide `Truck` in `--muted-foreground`. Same footprint as the photo so the layout matches. Decorative: `aria-hidden`. |
| `AB 1234 CJ` | `vehicle.plate_number` | Display size (≈40px bold). |
| `Foton Auman · 2016` | `{make} {model} · {year}` | Muted, as in the reference. |
| Driver Assigned + avatar + name | `GET /vehicles/{id}/assignments` → the entry with `released_at == null` → `GET /drivers/{driver_id}` | `InitialsAvatar` + "Driver assigned" + `full_name`, linking to `/foundation/drivers/{id}`. No active assignment: "No driver assigned" (muted), plus an "Assign" link for A/FM. **M cannot read assignments**, so the whole driver row is omitted for M rather than shown as "unassigned". |
| Phone pill `+62 812…` | `driver.phone` | Orange-outline pill (`border-primary text-primary-strong`), a `tel:` link. |
| Odometer | `vehicle.current_odometer` | `MetaItem`, `Gauge` icon, "87,420 km" via `Intl.NumberFormat`. |
| Fuel Type | `vehicle.fuel_type` | `MetaItem`, `Fuel` icon, title-cased label. |
| First Registered | Replaced | **VIN**: `MetaItem`, `Hash` icon, `font-mono`, with a copy button. |

**Also shown** (below the meta row, muted, small): the service interval ("Service every
10,000 km / 6 months") when set. It comes from `service_interval_km` / `_months`.

### 2.3 KPI tiles (2×2)

| Reference tile | Replacement | Source | Roles |
| --- | --- | --- | --- |
| Fuel Efficiency 8.2 km/L (green) | **Cost per km** | `GET /fuel/summary?month={current YYYY-MM}` → `by_vehicle[vehicle_id].avg_cost_per_km` (PKR/km). Null or vehicle absent → "—" with the caption "No fuel logs this month" | A/FM |
| Total Trips 24 (blue) | **Trips (30 days)** | Count of `GET /trips?vehicle_id={id}&date_from={today−30d}` | A/FM/D (D: counts own trips only, captioned "Your trips") |
| Utilization 78% (amber) | **Compliance** | `GET /vehicles/{id}/compliance` → count of `status == "overdue"`. 0 → "All current" (success); > 0 → "{n} overdue" (warning). A `due_soon` count goes in the caption | all |
| Cost per km IDR 2.340 (purple) | **Fuel cost (month)** | `by_vehicle[vehicle_id].total_cost` in PKR | A/FM |

Tiles the role can't see are **not rendered**; the grid collapses (e.g. M sees only
Compliance, D sees Trips + Compliance). Each tile has its own `QueryRegion`, so a failure is
isolated to that tile.

### 2.4 Maintenance panel ("Maintenance Overview")

`SectionPanel` (`Wrench` icon). The `…` menu has "Open in Maintenance" → `/maintenance?vehicle_id={id}`.

**Scheduled Service** (`InnerCard`)
- Source: `GET /vehicles/{id}/compliance` (all roles), items with `status` of `overdue`,
  `due_soon` or `never_performed`, overdue first.
- A `DueRow` per item:
  - service-type icon + label from `rule`;
  - right-aligned text built from the backend fields as-is: "Due in {km_remaining} km" /
    "Due in {days_remaining} days" / "Overdue" / "Never performed";
  - a status pill.
- Header action: the reference's "+ Add Schedule" becomes **"+ Log service"** (A/M, the
  maintenance write roles). It opens the maintenance log form from plan 06, prefilled with
  `vehicle_id`. Compliance rules are org-wide by make/model, so they're managed in
  `/maintenance`, not here.
- Empty: "No compliance rules apply to this vehicle" or "Everything is up to date"
  (success), depending on whether `items` is empty or all are compliant.

**Service History** (`InnerCard`, `TimelineList`)
- Source: `GET /maintenance?vehicle_id={id}` (A/FM/M), newest first, limited to 5 with
  "View all".
- Rows: date · service type label · cost (PKR, when present) · mechanic name (muted), and a
  "Report" badge when `mechanic_report` is present.
- **D cannot read maintenance**, so this card is omitted for D.

### 2.5 Trip performance panel

`SectionPanel` (`ChartLine` icon), with a range `ToggleGroup` in the header ("7 days",
"30 days", "90 days"; default 30) where the reference has its "Last 30 days" select.

| Part | Source | Rendering |
| --- | --- | --- |
| **Daily distance driven (km)** | `GET /trips?vehicle_id={id}&date_from={range start}` | `AreaTrendChart`: trips grouped by `start_time` date, summing `distance_km`. Days with no trips = 0, so the chart has a continuous x-axis. **Annotations**: days that have an anomalous fuel log (from the callout query below) get a marker chip "Fuel anomaly", replacing the reference's "Braking Events" chip. |
| **Callout** (replaces "Hard Braking Events Detected!") | `GET /fuel?vehicle_id={id}&date_from={range start}` → the newest with `is_anomalous: true`; else `GET /incidents` filtered to this `vehicle_id` with `resolution_status in (open, investigating)` | `Callout` (warning tokens, `TriangleAlert`). Fuel anomaly: "Unusual fuel cost on {date}", "Cost per km was {cost_per_km} PKR, more than 20% off this vehicle's 3-month average." Incident: "{n} open incident(s)", "Latest: {type}, {severity} on {date}". The chevron links to the record. **Neither → no callout** (no empty warning box). |
| **Recent trips table** (replaces the Route table) | Same trips query | `DataTable`, compact, last 5: Date · Distance (km) · Duration (from `end_time − start_time`, formatted "2h 15m") · Fuel used (L, `fuel_consumed`, or "—"). |

- **Roles:** A/FM see everything. D sees their own trips and fuel (the backend scopes them),
  so the panel title becomes "Your trips on this vehicle". **M has no trip or fuel access**,
  so the panel is omitted for M.
- **Incident filtering note:** `GET /incidents` has no `vehicle_id` filter (only `type`,
  `severity`, `status`), so filter by `vehicle_id` client-side after requesting
  `status=open` and `status=investigating`. Add "`vehicle_id` filter on `/incidents`" to the
  backend gaps list in 00 §6.

### 2.6 Health panel ("Vehicle Health Score")

`SectionPanel` (`HeartPulse` icon). **A/FM only**, since `/dashboard/fleet-health` is gated.
For M/D, the panel is omitted and the grid reflows.

- **Source:** `GET /dashboard/fleet-health` → the entry whose `vehicle_id` matches. Shares the
  cached query with the dashboard. Retired vehicles aren't in the list, so show the note
  "Health isn't scored for retired vehicles."
- **Gauge:** `HealthGauge size="lg"`, score, "/100".
- **Label mapping** (UI-only, since the backend returns just a number; document the
  thresholds in a tooltip):

  | Score | Label | Color |
  | --- | --- | --- |
  | ≥ 75 | Good | success |
  | 50–74 | Fair | warning |
  | < 50 | Poor | destructive |

- **"Health signals"** list (replaces "AI Diagnostic Results"). One `SignalRow` per signal,
  in this order:

  | Signal | Title | Detail (static, describes how the backend scores it) | Links to |
  | --- | --- | --- | --- |
  | `compliance` | Compliance | "Service rules met on schedule" | the Scheduled Service card (scroll) |
  | `incidents` | Incidents | "Incidents in the last 90 days" | `/accountability?vehicle_id=` |
  | `maintenance_currency` | Maintenance | "Overdue or upcoming service" | `/maintenance?vehicle_id=` |
  | `fuel_efficiency` | Fuel efficiency | "Cost per km vs the previous period" | `/fuel?vehicle_id=` |

  Each row shows its score as a small pill (same thresholds) or **"n/a" when null** (never 0).
  Nothing in this panel is labeled "AI".

### 2.7 Assign / Release driver (A/FM)

| Action | Form (`VehicleAssignRequest` / `VehicleReleaseRequest`, both `extra="forbid"`) | Behaviour |
| --- | --- | --- |
| Assign | `driver_id` (select from `GET /drivers`, status `active` only), `assigned_at` (datetime, default now), `start_odometer` (int > 0, default `current_odometer`), `take_condition` (good / fair / poor), `take_notes?` | `POST /vehicles/{id}/assign`. **409** (already assigned) → inline "This vehicle already has a driver" with a Refresh button. **400** (vehicle/driver not active) → inline message. |
| Release | `released_at` (default now), `end_odometer` (int > 0, ≥ start), `leave_condition`, `leave_notes?` | **Confirm dialog first** (a destructive-class action, per CLAUDE.md §6), then `POST /vehicles/{id}/release`. |

- **On success:** invalidate `vehicleKeys.assignments(id)`, `vehicleKeys.detail(id)`,
  `driverKeys.assignments(driverId)` and `dashboardKeys.all`, then toast.
- **No optimistic update:** custody changes are never optimistic (CLAUDE.md §5.1).

### 2.8 Role summary

| Region | A | FM | M | D |
| --- | :-: | :-: | :-: | :-: |
| Hero (vehicle fields) | ✓ | ✓ | ✓ | ✓ |
| Hero driver row + Contact | ✓ | ✓ | — | ✓ |
| Tiles: Cost/km, Fuel cost | ✓ | ✓ | — | — |
| Tile: Trips | ✓ | ✓ | — | ✓ (own) |
| Tile: Compliance | ✓ | ✓ | ✓ | ✓ |
| Scheduled service | ✓ | ✓ | ✓ | ✓ |
| Service history | ✓ | ✓ | ✓ | — |
| Trip performance | ✓ | ✓ | — | ✓ (own) |
| Health | ✓ | ✓ | — | — |
| Assign / Release | ✓ | ✓ | — | — |
| Log service | ✓ | — | ✓ | — |
| Report incident | ✓ | ✓ | — | ✓ |

Still handle a **403 on each region** as `AccessDenied` for that region, in case the matrix
drifts. A **404 on `GET /vehicles/{id}`** renders a page-level not-found state ("This vehicle
doesn't exist or was removed") with a link back to the list.

### 2.9 Data loading

- The Server Component `page.tsx` prefetches `GET /vehicles/{id}` so the hero paints first.
  Every other region is a client `QueryRegion` with a skeleton shaped like it: the hero
  skeleton matches hero geometry, the chart skeleton is a frame, the tiles skeleton is a
  2×2 grid.
- Requests fan out in parallel; none waits on another, except driver-by-id, which depends on
  the active assignment.
- Money and decimals go through `lib/api/decimal.ts`. Nothing is recomputed (`cost_per_km`,
  `is_anomalous` and `health_score` are displayed as-is).

## 3. Drivers (brief)

- **`/foundation/drivers`:**
  - `DataTable` of name, license number, **license expiry** (a warning pill when it falls
    within 30 days, destructive when expired), phone, status;
  - A/FM create/edit/delete, with `user_id` linking as an optional select.
- **`/foundation/drivers/[id]`:**
  - a hero like the vehicle one: `InitialsAvatar`, name, license, phone pill;
  - current vehicle from `GET /drivers/{id}/assignments` → `current_assignment`, with
    `total_vehicles_driven` as a tile;
  - an assignment history table (`history[]`: vehicle, assigned/released, duration_hours,
    conditions);
  - a `TimelineList` from `GET /drivers/{id}/timeline` (trips, reports, incidents).
- **Access:** timeline and assignments are A/FM/D (D: own id only, otherwise 403 →
  `AccessDenied` for the region). M sees only the basic driver fields.

## 4. Suppliers (brief)

- `/foundation/suppliers`: `DataTable` from `GET /suppliers?sort=reliability_score`, with
  reliability shown as a decimal string formatted to one decimal place.
- A/FM create/edit in a `Dialog`. **No detail page and no delete**, because the backend has
  no GET-by-id or DELETE.

## 5. Tests

- A region-mapping test per role, driving the role summary table above with MSW: assert
  which requests fire and which regions render.
- Hero: active vs no assignment; M without a driver row; phone as a `tel:` link.
- Tiles: `avg_cost_per_km` null → "—"; vehicle missing from `by_vehicle`; compliance
  "All current" vs "{n} overdue".
- Trip panel: grouping trips by day (including zero days); callout priority (fuel anomaly >
  open incident > none); the duration formatter.
- Health: null signal → "n/a"; label thresholds at 49/50/74/75; retired vehicle note.
- Assign/Release: form validation (`extra="forbid"`-safe payload), a 409 inline message,
  the confirm dialog on release, the invalidation calls.
- A 404 vehicle → not-found state.

## 6. Exit criteria

- [ ] Side-by-side with the reference at 1440px: same grid, spacing, radii, panel nesting,
      tile style, chart style, gauge and callout styling. Differences are **only** the
      documented replacements from 00 §3.
- [ ] Every role checked at 1440px and 375px; hidden regions reflow without gaps.
- [ ] A vehicle with no data (fresh) shows designed empty states in every region; a vehicle
      with seeded fuel/trip/maintenance data shows real values.
- [ ] build, lint and tests pass.
