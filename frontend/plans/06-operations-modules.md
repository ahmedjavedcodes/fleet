# 06 — Operations Modules (scoped)

**Status:** built at a reduced scope on 2026-09-29, under a tight session token budget —
see the per-module notes below for what shipped vs. what's deferred. Before picking up a
deferred piece, re-check the endpoints against `backend/app/api/*.py`, since they may have
moved, and expand it into a detailed plan the way 04/05 are written.

**Built this pass, all four routes:**
- **Fuel & Trips** (`/fuel`): tabs for Fuel logs (table + log-fuel form), Trips (table +
  log-trip form), Summary (A/FM: KPI tiles + by-vehicle table). **Not built:** receipt
  upload/`upload_status` display, the driver-facing mobile-first layout polish.
- **Maintenance** (`/maintenance`): Service log only (table + log-service form, `?vehicle_id=`
  pre-fill honored, D gets `AccessDenied`). **Not built:** mechanic report form,
  upcoming/overdue calendars, compliance rules CRUD, inventory, purchase orders — the page
  says so inline rather than pretending they exist.
- **Accountability** (`/accountability`): tabs for Incidents (table + report form + A/FM
  resolve dialog, `?vehicle_id=&new=1` pre-fill honored) and Shift reports (table + append-only
  submit form, no edit action per the backend's 405). **Not built:** the driver-picker
  timeline view (plan §3's third row) — a driver's own timeline is still reachable from
  their detail page (plan 05).
- **Assignment** (`/assignment`): the custody board (fans out `GET /vehicles` then
  `GET /vehicles/{id}/assignments` per vehicle, same assign/release dialogs as vehicle
  detail — promoted to `components/fleet/assign-release-dialog.tsx` since a second page now
  uses them). **Not built:** the "who had it on…" date-lookup region.

**Not done at all this pass, for the same budget reason:** live-browser verification with
seeded data, and the full test matrix from §-level "Tests" sections in 04/05's style — only
build/lint/typecheck/test (473 tests) were run as verification.

**Depends on:** 03. All modules reuse the primitives (`SectionPanel`, `KpiTile`,
`DataTable`, `StatusPill`, `TimelineList`, `Callout`) and follow the page-state rules from
CLAUDE.md §6.

Modules: **Fuel & Trips** (`/fuel`), **Maintenance** (`/maintenance`), **Accountability**
(`/accountability`), **Assignment** (`/assignment`).

---

## 1. Fuel & Trips: `/fuel`

**Access:** A, FM, D. Writes: A, D. Summary: A, FM. Drivers see only their own rows (the
backend scopes them).

| Tab / region | Endpoints | Key UI |
| --- | --- | --- |
| Summary (A/FM) | `GET /fuel/summary?month=YYYY-MM` | Month picker. `KpiTile`s for total cost, total liters and average cost/km. A `by_vehicle` table (vehicle, cost, liters, avg cost/km), with each row linking to the vehicle. |
| Fuel logs | `GET /fuel?vehicle_id&driver_id&date_from&date_to&skip&limit` | **The only server-paginated list** (`limit` ≤ 500): use `skip`/`limit` with `keepPreviousData`. Columns: date, vehicle, driver, odometer, liters, price/L, total (PKR), cost/km (**as-is**, "—" when null on a vehicle's first log), an anomaly `StatusPill` when `is_anomalous`, and a receipt icon. |
| Log fuel (A, D) | `POST /fuel` (`FuelLogCreate`) | Mobile-first form (drivers use phones): vehicle, date, odometer, liters, price/L, notes. A 400 (odometer not increasing) goes on the odometer field. A **422 with a string `detail`** for a driver without a profile → form-level "Your account isn't linked to a driver profile." |
| Edit (A, D) | `PUT /fuel/{id}` | A driver's `driver_id` is dropped silently by the backend, so don't show that field to D. |
| Receipt upload | `POST /fuel/{id}/receipt` (multipart `file`: pdf, jpeg, png, webp) | Pre-validate type and size. **409 = a receipt already exists**, so hide the upload once `receipt` is present and show `upload_status` (pending / parsed / failed) plus `parsed_data` if parsed. |
| Trips | `GET /trips?driver_id&vehicle_id&date_from&date_to`, `POST /trips` (A, D) | Table: date, vehicle, driver, distance (km), duration, fuel used (L). **Start and end are both required**, so there's no "trip in progress" UI and no live anything. |

**Invalidation:**

- a fuel log → fuel lists, `fuelKeys.summary`, `dashboardKeys.fuelTrends` and the vehicle
  detail tiles;
- a trip → trip lists and the vehicle trip panel.

**Never** compute cost/km or anomalies client-side.

## 2. Maintenance: `/maintenance`

**Access:**

- Read: A, FM, M. **Log write: A, M.**
- Upcoming/overdue: A, FM.
- Inventory/PO read: A, FM, M; write: A, FM.
- Compliance rules read: A, FM, M; write: A, FM.
- D: no access (`AccessDenied`).

| Tab | Endpoints | Key UI |
| --- | --- | --- |
| Service log | `GET /maintenance?vehicle_id&service_type&date_from&date_to`, `POST`, `PUT /{id}` | `TimelineList` or table. Create form: vehicle, date, odometer at service, `ServiceType` select, description, cost (decimal string), mechanic name, next due km/date. |
| Mechanic report | `POST /maintenance/{id}/mechanic-report` (A, M) | Diagnostic notes, findings, actions, `parts_used [{part_id, qty}]` (part picker from `/inventory`), recommendations. The **create response carries `low_stock_alerts`**: show them as a warning `Callout` right after submit. |
| Upcoming / overdue (A/FM) | `GET /maintenance/upcoming?window_km=1000`, `GET /maintenance/overdue` | `DueRow` lists using the backend's `km_remaining` as-is. |
| Compliance | `GET /compliance/rules?make&model&service_type`, `POST/PUT /compliance/rules`, `GET /compliance/status` | Rules table (A/FM edit). Status per vehicle with `compliant / due_soon / overdue / never_performed` pills. |
| Inventory | `GET /inventory?category&supplier_id&compatible_make&compatible_model`, `GET /inventory/low-stock`, `POST/PUT` (A/FM) | Low-stock banner with the backend's `deficit`. Parts table. |
| Purchase orders | `GET /purchase-orders?status&supplier_id&date_from&date_to`, `POST/PUT` (A/FM), `PATCH /{id}/receive` | Status pills (`pending / shipped / received / cancelled`). Receive → **confirm**, then show the `stock_updates[]` result. Invalidate inventory and low-stock. |

`?vehicle_id=` in the URL pre-filters the service log (linked from vehicle detail).

## 3. Accountability: `/accountability`

**Access:** A, FM, D. Resolve: A, FM. Shift-report write: A, D. D sees only their own records.

| Tab | Endpoints | Key UI |
| --- | --- | --- |
| Incidents | `GET /incidents?type&severity&status`, `POST /incidents` (A/FM/D), `PUT /incidents/{id}` (A/FM, **resolution only**) | Severity always shown as label + color (`minor / moderate / severe / critical`, `--sev-*` tokens). Types: `damage / violation / near_miss`. **Incidents are immutable**: the detail sheet shows every field read-only, and only `resolution_status` + `resolution_notes` are editable (A/FM). Estimated cost in PKR. |
| Shift reports | `GET /driver-reports?driver_id&vehicle_id&condition`, `POST /driver-reports` (A/D) | **Append-only**: never render an edit or delete action (PUT/PATCH return 405). Fields: shift date, vehicle condition (`good / fair / poor`), handover notes, issues reported. |
| Driver timeline | `GET /drivers/{id}/timeline` | Driver picker (A/FM). D is locked to their own id. `TimelineList` with record-type icons. |

**Report incident** from the vehicle detail page (plan 05) opens this module's create form
prefilled with `vehicle_id`. Incidents are **never** optimistically updated.

## 4. Assignment: `/assignment`

**Access:** A, FM (write + all history); D (own history, any vehicle's history).

**Domain rules** (CLAUDE.md §2.1):

- Assignments are **custody records** (`assigned_at` / `released_at`), **not a scheduler**.
  No calendar UI.
- There is **no "list all assignments" endpoint**. History is per vehicle
  (`GET /vehicles/{id}/assignments?target_date=`) or per driver
  (`GET /drivers/{id}/assignments`).

| Region | Endpoints | Key UI |
| --- | --- | --- |
| Current custody board (A/FM) | `GET /vehicles`, then `GET /vehicles/{id}/assignments` per vehicle (fan out; cap concurrency) | Table: vehicle, current driver or "Unassigned", since, and Assign/Release actions (same dialogs as plan 05 §2.7, shared from `components/fleet/`). If the fleet is large, this fan-out is expensive; flag it as a backend gap ("list active assignments") before building. |
| "Who had it on…" lookup | `GET /vehicles/{id}/assignments?target_date=YYYY-MM-DD` | Vehicle + date picker → the assignment(s) covering that date. Useful for incident attribution. |
| Driver history | `GET /drivers/{id}/assignments` | `current_assignment`, `total_vehicles_driven`, and a `history[]` table with `duration_hours` (null = active). |

**Invalidation:** vehicle and driver assignment keys, plus `dashboardKeys.all`. Never
optimistic.

## 5. Backend gaps surfaced by these modules

Add these to [00](00-design-analysis.md) §6 when the module is detailed:

- No "list active assignments" endpoint, which the custody board needs.
- No pagination or totals on maintenance, incidents, trips or inventory lists.
- No `vehicle_id` filter on `/incidents` (already listed).
