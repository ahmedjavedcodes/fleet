# Spec 05 — Strategic Insights

**Derived from:** [`backendPlan.md`](../backendPlan.md#problem-5--strategic-insights) · [`plans/05-strategic-insights.md`](../plans/05-strategic-insights.md)
**Status:** Ready for execution — **build last**
**Depends on (hard):** service-layer functions from Specs 01 (`fuel_service`), 02 (`inventory_service`), 03 (`maintenance_service`, `compliance_service`), 04 (`incident_service` — for open-incident counts). Do not begin until those functions exist and are stable.

---

## 1. Problem Statement

The fleet manager already has fuel data (Spec 01), parts data (Spec 02), maintenance/compliance data (Spec 03), and accountability data (Spec 04) — but sees each in isolation. Vehicle #14's fuel cost spiking, a mechanic's fuel-line note, an overdue inspection, and two recent driver incidents might all point to the same problem asset, but nothing assembles that picture. The insight already exists in the data; no view currently synthesizes it into something a manager (or, later, an AI agent) can act on in one glance.

---

## 2. Functional Requirements

| ID | Requirement |
|---|---|
| FR-5.1 | The system shall provide a fleet-wide summary: total vehicles, active drivers, current month's fuel cost, count of overdue maintenance items, count of low-stock parts, count of open incidents. |
| FR-5.2 | The system shall provide a 12-month (configurable) fuel cost trend, monthly totals and average `cost_per_km`. |
| FR-5.3 | The system shall provide a 30-day (configurable) maintenance calendar combining upcoming and overdue service items. |
| FR-5.4 | The system shall provide a per-vehicle composite health score (0–100) combining compliance status, recent incident count, maintenance currency, and fuel efficiency trend. |
| FR-5.5 | Every aggregation shall be computed by calling the existing domain service functions from Specs 01–04, not by re-implementing their queries. |
| FR-5.6 | No endpoint in this domain shall perform a write of any kind. |
| FR-5.7 | The system shall introduce no new persisted tables for this problem. |
| FR-5.8 | The system shall never generate natural-language summaries or narrative insights — out of scope for this module. |

---

## 3. Behaviour

### 3.1 Summary (`GET /dashboard/summary`)

- `total_vehicles` = count of non-retired vehicles in the organization.
- `active_drivers` = count of drivers with `status = active`.
- `month_fuel_cost` = `fuel_service.get_monthly_summary(current_month).total_cost`.
- `overdue_maintenance_count` = `len(maintenance_service.list_overdue())`.
- `low_stock_parts_count` = `len(inventory_service.list_low_stock())`.
- `open_incidents_count` = count of incidents with `resolution_status in (open, investigating)`.
- All six values reflect the same instant; the endpoint issues no writes.

### 3.2 Fuel trends (`GET /dashboard/fuel-trends?months=12`)

- Returns one point per month for the requested range, including months with zero fuel logs (`total_cost = 0`, `avg_cost_per_km = null`), sourced from `fuel_service`'s aggregation (extended to accept a month range rather than called once per month, to avoid N round trips).

### 3.3 Maintenance calendar (`GET /dashboard/maintenance-calendar?window_days=30`)

- Merges `maintenance_service.list_upcoming` (items due within the window) and `maintenance_service.list_overdue` (**all** currently overdue items, regardless of how long overdue — an item does not drop off the calendar for being "too overdue").

### 3.4 Fleet health (`GET /dashboard/fleet-health`)

For each active vehicle, compute four normalized (0–100) signals and combine them into one score:

1. **Compliance signal** — from `compliance_service.get_vehicle_compliance`: average across applicable rules, `compliant=100`, `due_soon=60`, `overdue=20`, `never_performed=0`. A vehicle with no applicable rules excludes this signal from the average entirely rather than defaulting it to any fixed value.
2. **Incident signal** — count of incidents in the last 90 days for the vehicle, mapped through fixed, documented buckets (e.g. `0→100, 1→70, 2→40, 3+→10`).
3. **Maintenance-currency signal** — derived from the vehicle's overdue/upcoming state: not overdue/due_soon `=100`, due_soon `=60`, overdue `=10`.
4. **Fuel-efficiency signal** — comparison of the vehicle's trailing 3-month `cost_per_km` average against its prior 3-month average: flat/improving `=100`, moderate worsening `=60`, worsening beyond the Spec 01 20% anomaly threshold `=20`.
5. **`health_score`** = weighted average of whichever signals are available (weights fixed and documented in code — e.g. compliance 30%, incidents 25%, maintenance 25%, fuel 20% — subject to confirmation before being treated as final business logic).

---

## 4. Constraints

1. **Read-only, always.** No function in `dashboard_service.py` opens a write transaction, under any circumstance.
2. **No new models or tables.** Every number here is derived from Specs 01–04's existing tables via their existing service functions.
3. **No duplicated query logic.** If a number is already computed by a Spec 01–04 service function, this module calls that function (extending its signature if needed, e.g. adding a date-range parameter) rather than writing a second, parallel implementation of the same SQL.
4. **Organization scoping** applies identically to every aggregation — a dashboard for one organization never includes another's data, even in a fleet-wide total.
5. **Missing signals are excluded, not defaulted.** The fleet-health weighted average must never silently treat "no applicable compliance rules" as either full or zero compliance.
6. **This is the last problem to be built** — it cannot be implemented, let alone tested end-to-end, before Specs 01–04's relevant service functions exist.
7. **These endpoints are the ones safe to expose over MCP to `ai_agents` unmodified**, precisely because they are read-only and side-effect-free — this property must be preserved, not incidentally broken by a future change that adds a write path here.

---

## 5. Edge Cases and Error Handling

| # | Scenario | Expected behavior |
|---|---|---|
| EC-1 | A month in the fuel-trends range has zero fuel logs | Appears in the response with `total_cost: 0`, `avg_cost_per_km: null` — never omitted from the series. |
| EC-2 | A maintenance item is 200 days overdue | Still appears in `/dashboard/maintenance-calendar` despite the 30-day window, since overdue items are never window-filtered. |
| EC-3 | An upcoming item is due in 90 days | Excluded from the 30-day calendar. |
| EC-4 | A vehicle has no applicable `ComplianceRule` at all | Its health score is computed from the remaining three signals only; the compliance signal contributes nothing to the weighted average, not a 0. |
| EC-5 | A newly added vehicle with no fuel history at all | Fuel-efficiency signal is excluded (insufficient trailing data), not defaulted to a penalty or a perfect score. |
| EC-6 | Organization has zero vehicles | `/dashboard/summary` returns all-zero counts, not an error; `/dashboard/fleet-health` returns an empty list. |
| EC-7 | Two organizations both request `/dashboard/summary` concurrently | Each sees only its own organization's numbers — no leakage under concurrent load. |
| EC-8 | An underlying Spec 01–04 service function's behavior changes (e.g. anomaly threshold) | The dashboard's fuel-efficiency signal reflects it automatically, since it calls that function rather than re-implementing the threshold — verified via the regression guard in AC-2. |
| EC-9 | `months`/`window_days` query params are zero, negative, or absurdly large | Validated with sane bounds (e.g. `1 <= months <= 24`); reject out-of-range values with `422` rather than running an unbounded query. |

---

## 6. Acceptance Criteria

- [ ] **AC-1:** `GET /dashboard/summary` values match hand-computed totals over seeded multi-domain data (fuel, maintenance, inventory, incidents, vehicles, drivers).
- [ ] **AC-2:** A regression test confirms `dashboard_service.get_summary` invokes `maintenance_service.list_overdue` and `inventory_service.list_low_stock` rather than querying those tables directly (e.g. via a spy/mock), guarding against logic duplication creeping in later.
- [ ] **AC-3:** `GET /dashboard/fuel-trends?months=6` returns exactly 6 monthly points, including any with zero activity, matching manual aggregation.
- [ ] **AC-4:** `GET /dashboard/maintenance-calendar` includes an item overdue by 60 days even when `window_days=30`, and excludes an upcoming item due in 90 days.
- [ ] **AC-5:** `GET /dashboard/fleet-health` excludes the compliance signal (not zeroes it) for a vehicle with no applicable rules, verified by comparing its score against an otherwise-identical vehicle that does have rules and is fully compliant.
- [ ] **AC-6:** Fleet-health signal bucket boundaries (e.g. incident count thresholds) are covered by explicit boundary tests once the thresholds are finalized and documented in code.
- [ ] **AC-7:** No write (INSERT/UPDATE/DELETE) is reachable from any function in `dashboard_service.py` — verified by code review or a static check, not just absence of failing tests.
- [ ] **AC-8:** No endpoint in this domain returns or is influenced by another organization's data, including in fleet-wide totals.
- [ ] **AC-9:** Out-of-range `months`/`window_days` query parameters are rejected with `422` rather than silently clamped or causing an unbounded query.
