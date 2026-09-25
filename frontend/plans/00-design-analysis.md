# 00 — Design Analysis

**Reference:** [assets/fleetyo-vehicle-detail.png](assets/fleetyo-vehicle-detail.png): a
"FleetYo" vehicle-detail screen, 2555×1490. It is a photo of a monitor, so colors are
slightly washed out and every measured value below is **approximate**. Phase 01
re-verifies them before they become final tokens.

This document is the input for filling CLAUDE.md §1.1 and §1.2. It also records where the
design conflicts with CLAUDE.md's non-negotiables and how each conflict is resolved.

---

## 1. Anatomy of the reference

### App shell

- **Sidebar** (white, rounded, bordered):
  - brand logo ("FleetYo." + orange truck mark) and a collapse toggle (`PanelLeft` icon);
  - nav grouped under small muted section labels: *Main Menu, Fleet, Operations,
    Monitoring, Insights, System*. Groups are separated by thin dividers;
  - nav item = outline icon + label. **Active item**: orange icon and text on a soft orange
    tint, rounded;
  - **user card** pinned to the bottom: avatar, full name, role ("Operational Manager"),
    up/down chevron (opens a menu).
- **Topbar** (white, rounded, bordered, detached from the sidebar):
  - breadcrumbs `Fleet / Vehicles / AB 1234 CJ - Foton Auman 2016` with the last crumb bold;
  - a centered **status pill** (green dot + "On Route" + route text);
  - right side: outline buttons with icon + label ("Contact Driver", "Assign Task"), a
    vertical divider, then square icon-only buttons (flag, share).

### Page content

- **Hero card**:
  - vehicle image on the left;
  - large bold plate number (`AB 1234 CJ`) with a muted `Make · Year` subtitle;
  - assigned driver (avatar + "Driver Assigned" label + name) next to an orange-outline
    phone pill;
  - a 3-up meta row (icon + muted label + value) separated by dotted vertical dividers:
    Odometer, Fuel Type, First Registered.
- **KPI tiles**: a 2×2 grid to the right of the hero. Each tile is a colored rounded-square
  icon, a label, a large number and a small muted unit. Colors: green, blue, amber, purple.
- **Three panels** (a light-grey outer panel holding white inner cards):
  1. *Maintenance Overview* (header icon + title + `…` menu):
     - "Scheduled Service" card with a "+ Add Schedule" text action and bordered rows
       (icon, name, right-aligned "Due in 820 km" / "Due on 15 Jul 2026");
     - "Service History" card with a vertical timeline (radio dot, date, then service
       name and cost).
  2. *Trip Performance* (with a "Last 30 days" select):
     - "Daily Distance Driven (km)" area chart: orange line, dot markers, orange→transparent
       gradient fill, dashed gridlines, an annotation tooltip;
     - an amber **warning callout** (triangle icon, title, detail, chevron);
     - a table with a grey header row: Route, Distance, Duration, Fuel Used.
  3. *Vehicle Health Score*:
     - semicircle gauge (lime→green gradient on a grey track), large "76 /100" and a green
       "Good" label;
     - "AI Diagnostic Results": bordered rows with a title, muted detail and a chevron.

### Recurring visual rules

- **Flat.** Surfaces are separated by 1px light borders and background steps. No visible
  drop shadows.
- **Two-level surfaces.** A grey outer panel (`#F7F7F7`) holds white inner cards. White top
  level cards sit on a white page.
- Generous radii, with outer containers rounder than inner rows.
- Numbers are large and bold with a small muted unit ("8.2 km/L", "78 %").
- Status always pairs color with text or an icon ("On Route" with a dot, "Good" under the
  gauge).

---

## 2. Measured tokens

Sampled pixel-by-pixel from the PNG (System.Drawing, max-chroma/min-luminance within each
region). Contrast ratios are against `#FFFFFF`.

### Color

| Proposed token | Measured | Contrast | Decision |
| --- | --- | --- | --- |
| `--primary` (brand fill, icons, chart line, focus ring) | `#F5781E` logo, `#EF772C` nav icon, `#D45A0F`–`#D96822` chart line | 2.8:1 | Use `#F5781E` for **non-text** only: fills, icons, chart strokes. |
| `--primary-strong` (orange text, primary button bg with white label) | *derived*, ≈ `#B8520F` | ≈ 4.9:1 | The measured active-nav text `#D16623` is only 3.7:1, which fails AA. Darken to the lightest shade that reaches 4.5:1; confirm in phase 01. |
| `--primary-soft` (active nav bg, orange tints) | `#FFF2EE` | — | As measured. |
| `--background`, `--card`, `--sidebar`, `--popover` | `#FFFFFF` | — | As measured. |
| `--panel` (outer panel), `--muted` | `#F7F7F7` | — | As measured. |
| table header surface | `#F5F5F5` | — | Map to `--muted` if visually indistinguishable; otherwise a separate `--table-head`. |
| `--border`, `--input` | `#ECECEC` (scans show `#E9E9E9`–`#EDEDED`) | — | `#ECECEC`. |
| `--foreground` | near-black (`#000000`–`#070707` in the photo) | ≈ 18:1 | `#111111`. Pure black reads harsh, and the photo crushes darks. |
| `--muted-foreground` | `#464646`–`#5D5D5D` | ≈ 6.6:1 at `#5D5D5D` | `#5D5D5D`. |
| unit text ("km/L", "trips") | `#D8D7D8` | ≈ 1.4:1 | **Rejected**: fails AA. Units use `--muted-foreground` at a smaller size. |
| `--success` (text) | `#36941A` "Good", `#41A139` "On Route" | ≈ 3.9:1 | Darken the text variant to reach 4.5:1 (≈ `#2E7D16`); keep `#36941A` for the dot and icon. |
| `--success-soft` | `#F0F8EF` (pill bg) | — | As measured. |
| `--warning` (fill) | `#F8AE0E` | — | As measured. |
| `--warning-soft` / `--warning-border` / warning icon | `#FFFBF3` / `#E5C597` / `#E1844D` | — | As measured. Warning *text* stays `--foreground`. |
| `--info` | `#2987DB` | ≈ 3.9:1 | Fills and icons only; a darker text variant if ever used as text. |
| `--accent-purple` | `#8D1BFF` | — | Tile and chart color only. |
| `--tile-green` / `-blue` / `-amber` / `-purple` | `#21B52E` / `#2987DB` / `#F8AE0E` / `#8D1BFF` | — | KPI icon squares with a white glyph (icons are non-text, so 3:1 applies). |
| `--chart-1` … `--chart-5` | orange `#F5781E`, blue `#2987DB`, green `#21B52E`, amber `#F8AE0E`, purple `#8D1BFF` | ≥ 3:1 on `--card` for strokes | Validate with the `dataviz` skill's checker in phase 01. |
| `--gauge-start` / `--gauge-end` / `--gauge-track` | `#EBF3A8` / `#80D765` / `#EFEFEF` | — | As measured. |
| `--destructive` | **not in the design** | — | *Derived.* A red that reaches 4.5:1 on white (≈ `#C8281E`). Labeled "derived" in CLAUDE.md. |
| `--sev-minor` / `-moderate` / `-severe` / `-critical` | **not in the design** | — | *Derived* from the palette: info blue / warning amber / primary orange / destructive red. Always paired with a text label (CLAUDE.md §1.3). |

### Shape, type, spacing, motion

| Token | Estimate from the reference | Status |
| --- | --- | --- |
| `--radius` scale | outer cards/panels ≈ 16px (`xl`), inner rows/cards ≈ 12px (`lg`), KPI icon tiles ≈ 10px (`md`), pills fully rounded | Re-measure in phase 01 with a pixel scan along card corners. |
| Elevation | none: border-only | `--shadow-card: none`. `--shadow-popover` is *derived* (dropdowns and popovers need separation). |
| `--font-sans` | geometric sans; closest match **Urbanist** (confirmed by the user) | Load via `next/font/google`. `--font-mono`: Geist Mono or JetBrains Mono (derived, for VINs and code). |
| Type scale | plate ≈ 40px bold; KPI numbers ≈ 32px semibold; panel titles ≈ 20px medium; body ≈ 16px; captions ≈ 13–14px | Re-measure in phase 01. |
| Spacing | base 4px; card padding ≈ 24px; gap between panels ≈ 16–20px; page gutter ≈ 16px | Re-measure in phase 01. |
| Motion | not observable in a still | *Derived*: `--ease-standard: cubic-bezier(0.2, 0, 0, 1)`, 150ms hover, 200ms overlays. |

### Dark mode

The reference is light-only. CLAUDE.md §1.2 requires a dark set, so phase 01 **derives**
one: near-black surfaces, the same hue family, and re-verified contrast. It is labeled
*derived* in CLAUDE.md so nobody mistakes it for part of the reference.

---

## 3. Conflicts with CLAUDE.md and how each is resolved

The design is a generic telematics template. CLAUDE.md's non-negotiables win (**no live
telemetry, no fake data, no client-side recomputation of backend metrics**). The user chose
to **keep each visual slot and fill it with real backend data**, dropping only what has no
honest replacement.

| # | Design element | Why it can't ship as drawn | Resolution |
| --- | --- | --- | --- |
| 1 | "Live Tracking" nav item | Live location is forbidden (non-negotiable #2) | **Dropped.** |
| 2 | "On Route · Surabaya → Malang" status pill | Implies real-time position | `VehicleStatus` pill: `active` / `maintenance` / `retired`, each with a color dot and label. |
| 3 | "Braking Events" chart annotation + "Hard Braking Events Detected!" callout | Telematics sensor data | The callout slot shows the most relevant **real** alert for the vehicle: the latest fuel log with `is_anomalous: true`, or an open incident. The chart annotation marks days with an anomalous fuel log. If there is neither, the callout is not rendered (no empty warning box). |
| 4 | "AI Diagnostic Results" | No AI diagnostics endpoint; labeling rule-based scores as AI would mislead | Renamed **"Health signals"**: one row per `fleet-health` signal (`compliance`, `incidents`, `maintenance_currency`, `fuel_efficiency`) with its 0–100 score and a one-line meaning. A `null` signal renders "n/a", never 0. |
| 5 | "Engine temperature is stable" | Sensor data | **Dropped.** |
| 6 | "Fuel Efficiency 8.2 km/L" | Needs client-side math over fuel logs. CLAUDE.md: display `cost_per_km`, never recompute | **Cost per km**: `avg_cost_per_km` from `GET /fuel/summary` → `by_vehicle[]`. |
| 7 | "Utilization Rate 78%" | No utilization data anywhere in the backend | **Compliance**: count of `overdue` items from `GET /vehicles/{id}/compliance` ("2 overdue" / "All current"). |
| 8 | "Cost per km IDR 2.340" | IDR; CLAUDE.md defaults to PKR | Becomes **Fuel cost (month)** from `by_vehicle[].total_cost`, since #6 already covers cost/km. Formatted with `Intl.NumberFormat`, currency PKR. |
| 9 | Truck photo | `VehicleResponse` has no image field | A neutral illustrated tile (soft `--panel` square with a large Lucide `Truck` icon). **Never** a stock photo that pretends to be this vehicle. |
| 10 | "First Registered 15 March 2020" | No registration date field | **VIN** in `--font-mono`, with copy-to-clipboard. |
| 11 | "Assign Task" button | No tasks domain in the backend | **Assign driver** / **Release driver** (A/FM only; release needs a confirm dialog). |
| 12 | Flag icon button | Unclear action | **Report incident** (A/FM/D can create incidents), as an icon button with a tooltip. |
| 13 | Share icon button | — | **Copy link** to this page, with a toast on success. |
| 14 | "Settings" nav (System group) | Not in the CLAUDE.md route map | **Omitted.** No dead UI (CLAUDE.md §7). |
| 15 | Route table "Surabaya → Malang" | Trips have no origin or destination fields | **Recent trips** table: Date, Distance (km), Duration, Fuel used (L). All values come straight from `TripLogResponse`; duration is `end_time − start_time`, formatted. |
| 16 | "Tasks", "Route", "Reports" nav items | No such domains | Not carried over. The nav comes from the CLAUDE.md route map (section 4 below). |
| 17 | User card "Operational Manager" | Must come from `/auth/me` | `user.full_name` + role badge (`Admin` / `Fleet Manager` / `Mechanic` / `Driver`). Initials avatar, since there is no user photo field. |
| 18 | Driver avatar photo | No photo field | Initials avatar. |
| 19 | "FleetYo." brand logo | The reference's brand, not ours | **FleetOps** wordmark, same style, next to the orange truck mark (`APP_NAME` in `src/lib/brand.ts`). |

**Derived metrics that are allowed.** Counting records and grouping backend values for a
chart is presentation, not recomputation:

- "trips in the last 30 days" = the length of `/trips?vehicle_id&date_from`;
- the daily distance chart = trip `distance_km` summed per day.

What stays forbidden is re-deriving a metric the backend owns (`cost_per_km`,
`is_anomalous`, `health_score`).

---

## 4. Navigation mapping

The design's grouped sidebar, filled with CLAUDE.md §2.1 routes. Every item is filtered by
`can(role, "nav:<route>")` from `lib/rbac.ts`. **A group whose items are all hidden is hidden
with its label.**

| Group | Item | Route | Lucide icon | Visible to |
| --- | --- | --- | --- | --- |
| Main Menu | Overview | `/dashboard` | `LayoutGrid` | A, FM, M, D |
| Main Menu | AI Assistant | `/chat` | `Sparkles` | A, FM, M, D |
| Fleet | Vehicles | `/foundation/vehicles` | `Truck` | A, FM, M, D |
| Fleet | Drivers | `/foundation/drivers` | `Users` | A, FM, M, D |
| Fleet | Suppliers | `/foundation/suppliers` | `Building2` | A, FM, M, D |
| Fleet | Assignment | `/assignment` | `ArrowLeftRight` | A, FM, D |
| Operations | Fuel & Trips | `/fuel` | `Fuel` | A, FM, D |
| Operations | Maintenance | `/maintenance` | `Wrench` | A, FM, M |
| Operations | Accountability | `/accountability` | `ShieldAlert` | A, FM, D |
| Knowledge | Documents | `/documents` | `FileText` | A, FM, M, D |
| Insights | Insights | `/insights` | `ChartColumn` | A, FM |
| Monitoring | Notifications | `/notifications` | `Bell` | A, FM, M, D |

`/foundation` in CLAUDE.md is one route. This plan splits it into
`/foundation/{vehicles,drivers,suppliers}` sub-routes plus `/foundation/vehicles/[id]`, and
`/foundation` redirects to `/foundation/vehicles`. **Phase 01 records this in CLAUDE.md
§2.1.**

Breadcrumbs follow the route: `Fleet / Vehicles / <plate> — <make> <model> <year>`.

---

## 5. Component inventory

Primitives derived from the reference. Each is built once, on tokens only, and lives in
`src/components/` (shared) or in a page's `_components/` until a second page needs it.

| Component | Seen in the design as | Built on | Plan |
| --- | --- | --- | --- |
| `SectionPanel` | Grey outer panel with header icon, title, optional action or `…` menu | `div` + tokens | 03 |
| `InnerCard` | White bordered card inside a panel ("Scheduled Service") | shadcn `Card` (customized) | 03 |
| `KpiTile` | Colored icon square + label + big number + unit | `Card` + `IconTile` | 03 |
| `IconTile` | Rounded colored square with a white glyph | `div` + `--tile-*` | 03 |
| `StatusPill` | Soft-bg pill with a colored dot and label | shadcn `Badge` variant | 03 |
| `Breadcrumbs` | Topbar trail, last crumb bold | `nav` + `ol` | 03 |
| `ActionButton` | Outline button with icon + label; square icon-only variant | shadcn `Button` variants | 03 |
| `MetaItem` | Icon + muted label + value (odometer, fuel type) | `dl` | 05 |
| `DueRow` | Bordered row: icon, name, right-aligned due text | `li` | 05 |
| `TimelineList` | Dotted vertical timeline with a date column and details | `ol` | 05 |
| `AreaTrendChart` | Orange line + gradient fill + dashed grid + markers | `recharts` `AreaChart` | 04, 05 |
| `HealthGauge` | Semicircle arc with gradient, score, label | SVG arc (inline, tokens) | 04, 05 |
| `SignalRow` | Title + muted detail + chevron | `button`/`a` row | 05 |
| `Callout` | Warning box with icon, title, detail, chevron | `div role="status"` + warning tokens | 05 |
| `DataTable` | Grey header row, light row separators, icon cells | shadcn `Table` (sticky header, tabular nums) | 03 |
| `InitialsAvatar` | User card and driver avatars | shadcn `Avatar` fallback | 03 |

---

## 6. Backend gaps

Things the design wants that the backend can't provide today. Hand this list to the backend
owners. **The frontend does not fake any of these.**

| Gap | Impact on the UI | Suggested backend change |
| --- | --- | --- |
| No vehicle photo | Illustrated icon tile instead of a photo | Optional `photo_url` on `Vehicle` + upload endpoint |
| No registration date | VIN shown instead of "First Registered" | `registered_at` on `Vehicle` |
| No assigned driver on `VehicleResponse` | Two extra requests: assignments → driver | Embed `current_assignment` (driver id, name, phone) in `VehicleResponse` |
| Health score only in `/dashboard/fleet-health` (A/FM), fleet-wide | Detail page fetches the whole fleet to show one score; M/D can't see it | `GET /vehicles/{id}/health`, readable by all roles |
| `GET /incidents` has no `vehicle_id` filter (only `type`, `severity`, `status`) | Vehicle detail filters incidents client-side | Add a `vehicle_id` query param |
| Trips have no origin or destination | No "Route" column | Optional `origin` / `destination` text fields on `TripLog` |
| Only `GET /fuel` is paginated, and no list returns a total | Client-side paging, no "x of y" counts | `skip` / `limit` + total count on every list |
| No logout endpoint, no refresh token, 60-minute JWT | Hard re-login every hour | Refresh token, or a longer session with a revocation list |
| `VehicleResponse` omits `created_at` / `updated_at` | No "Added on" in the list | Add both to the response |
| ~~`/documents` and `/memory` routers only on the `backend` branch~~ | **Resolved 2026-09-25**: `backend` + `ai-agents` merged into `frontend` (merge commit `39083ec`); both routers are registered in `backend/app/main.py` | — |
| No "list active assignments" endpoint | The custody board (plan 06) must fetch assignments one vehicle at a time | `GET /assignments?active=true` |
| `/memory` has no "list my sessions" endpoint | The chat history panel (plan 07) has nothing to list | `GET /memory/sessions` |
| No chat, notifications or NL-insights HTTP API (`ai_agents` has no web server) | Those pages ship "not available yet" states | The contracts proposed in CLAUDE.md §5.5 |
