# Spec 01 — Fuel Price Volatility

**Derived from:** [`backendPlan.md`](../backendPlan.md#problem-1--fuel-price-volatility) · [`plans/01-fuel-price-volatility.md`](../plans/01-fuel-price-volatility.md)
**Status:** Ready for execution
**Depends on:** Foundation models (`Organization`, `User`, `Vehicle`, `Driver`), `AuditMixin`, `OrgScopedMixin`, auth (`get_current_user`)

---

## 1. Problem Statement

A fleet manager running ~20 trucks has no visibility into per-vehicle running cost. Diesel prices fluctuate week to week; fill-ups are recorded on paper receipts scattered across stations. He cannot tell which trucks cost more to run, whether a truck's consumption has spiked (leaking fuel line, siphoning, a routing change), or what next month's fuel spend will look like. The data to answer these questions exists at the point of every fill-up — it just isn't captured or computed anywhere.

The system must turn every fill-up into a single comparable number — cost per kilometer driven — and surface it immediately when a fill-up deviates sharply from that vehicle's own recent history. No hardware, no GPS: the odometer reading is entered by the driver at the pump.

---

## 2. Functional Requirements

| ID | Requirement |
|---|---|
| FR-1.1 | The system shall allow an authenticated user to create a fuel log for a vehicle: date, odometer reading, liters filled, price per liter, total cost, optional driver, optional notes. |
| FR-1.2 | On creation, the system shall compute `cost_per_km` from the delta against the vehicle's previous fuel log's odometer reading, and store the result — not the formula. |
| FR-1.3 | The first fuel log ever recorded for a vehicle shall have `cost_per_km = null`. |
| FR-1.4 | On creation, the system shall update `Vehicle.current_odometer` if the new reading exceeds the currently stored value. |
| FR-1.5 | On creation, the system shall compare the new log's `cost_per_km` against the vehicle's trailing 3-month average `cost_per_km` and mark the log `is_anomalous = true` if the deviation exceeds 20%. |
| FR-1.6 | The system shall allow a user to attach a receipt file (image or PDF) to an existing fuel log via multipart upload, storing the file and recording `upload_status = pending`. |
| FR-1.7 | The system shall allow updating an existing fuel log's editable fields, recalculating `cost_per_km` using the same neighbor-lookup rule as creation. |
| FR-1.8 | The system shall allow listing fuel logs filtered by vehicle, driver, and date range. |
| FR-1.9 | The system shall allow retrieving a single fuel log together with its receipt's metadata (not its parsed content). |
| FR-1.10 | The system shall provide a monthly aggregation (total cost, average `cost_per_km`, per-vehicle breakdown) for dashboard consumption. |
| FR-1.11 | The system shall never parse receipt file contents, forecast future costs, or cross-reference anomalies with other domains' text — these are out of scope for this module. |

---

## 3. Behaviour

### 3.1 Create fuel log (`POST /api/v1/fuel`)

1. Resolve `organization_id` from the authenticated user's JWT — never from the request body.
2. Load the target `Vehicle` (organization-scoped, not soft-deleted). Not found → `404`.
3. Load the vehicle's most recent prior `FuelLog` (by `date`, tie-broken by `odometer_reading`, organization-scoped).
4. If a prior log exists:
   - `delta = new.odometer_reading - prior.odometer_reading`
   - If `delta <= 0` → reject with a validation error (do not divide by zero or store a negative/undefined value).
   - `cost_per_km = new.total_cost / delta`
5. If no prior log exists: `cost_per_km = null`, `is_anomalous = false` (never flagged on the first data point).
6. If `cost_per_km` is not null and the vehicle has at least the minimum number of prior non-null `cost_per_km` readings within the trailing 3 months: compute their average and flag `is_anomalous = true` when `abs(cost_per_km - avg) / avg > 0.20`.
7. Insert the `FuelLog` row with `cost_per_km` and `is_anomalous` frozen at their computed values.
8. If `odometer_reading > Vehicle.current_odometer`, update the vehicle in the same transaction.
9. Commit atomically. Any failure in steps 7–8 rolls back both.
10. Return the created log including computed fields.

### 3.2 Update fuel log (`PUT /api/v1/fuel/{id}`)

- Recomputes `cost_per_km` using the same delta rule against this log's chronological predecessor, reflecting any edited `odometer_reading`/`total_cost`.
- Does **not** cascade-recompute the chronologically-*next* log's `cost_per_km`, even though its predecessor's data just changed. This is intentional: computed values are frozen at their own creation time (see Constraints §4.3), and the edited log is the one being written now.
- Does not re-run anomaly detection against logs created after this one.

### 3.3 Attach receipt (`POST /api/v1/fuel/{id}/receipt`)

- Stores the uploaded file via the configured storage backend and records `file_path`, `file_type`.
- Sets `upload_status = pending`. The system never sets it to `parsed` or `failed` — only the AI module does, via a separate (future) mechanism.
- Does not read or interpret the file's contents.

### 3.4 Monthly summary (`GET /api/v1/fuel/summary`)

- Read-only aggregation: total cost and average `cost_per_km` for the requested month, both fleet-wide and broken down per vehicle.
- Must be implemented as a function reusable by the Problem 5 dashboard service, not duplicated there.

---

## 4. Constraints

1. **Organization scoping.** Every query filters by `organization_id` (from the JWT) and `is_deleted = false`. No cross-tenant read or write path exists.
2. **Computed fields are write-time, not read-time.** `cost_per_km` and `is_anomalous` are calculated once, at row creation (or explicit update), and stored. List/get endpoints never recompute them.
3. **Frozen values are not cascade-recomputed.** Editing a historical log does not retroactively touch other rows' stored computed values.
4. **Side effects share one transaction.** Creating/updating a `FuelLog` and updating `Vehicle.current_odometer` succeed or fail together — no partial writes, no queue, no async job.
5. **Odometer is monotonically non-decreasing via this workflow.** A fuel log with a lower odometer reading than the vehicle's current value never regresses `Vehicle.current_odometer`.
6. **File storage is separate from file interpretation.** The backend is a storage/status layer for receipts only; parsing is explicitly out of scope (`ai_agents`).
7. **`created_by` is stamped server-side** from the authenticated user; it is never client-supplied.
8. **No background jobs.** Anomaly detection and odometer updates run synchronously inside the request that triggers them.

---

## 5. Edge Cases and Error Handling

| # | Scenario | Expected behavior |
|---|---|---|
| EC-1 | First fuel log for a vehicle | `cost_per_km = null`, `is_anomalous = false`, `201` created. |
| EC-2 | New odometer reading ≤ previous log's reading | `400` validation error; no row is inserted; vehicle odometer untouched. |
| EC-3 | Fewer than the minimum rolling-average data points exist | `is_anomalous = false` regardless of the raw `cost_per_km` value — never flag on insufficient history. |
| EC-4 | New odometer reading is lower than `Vehicle.current_odometer` (e.g. correcting a bad entry on an older date) | The fuel log is still created/computed against its own chronological neighbor; `Vehicle.current_odometer` is **not** decreased. |
| EC-5 | Vehicle does not exist or belongs to another organization | `404`. |
| EC-6 | Receipt upload for a fuel log that already has one | Reject (`409`) or replace, per a single documented choice — do not silently create a second receipt row per log (schema enforces uniqueness on `fuel_log_id`). |
| EC-7 | Anomaly check's rolling average happens to be `0` or the log itself is the only one in the window | Guard the division; treat as insufficient history (EC-3), not a crash. |
| EC-8 | Concurrent creation of two fuel logs for the same vehicle in the same request window | Each computes its `cost_per_km` against whatever predecessor existed at the time of its own transaction; no explicit locking is required here since logs are historical facts, not mutable shared state like inventory stock. |
| EC-9 | `update_fuel_log` request omits fields that don't affect the delta (e.g. only `notes`) | `cost_per_km` recomputes to the same value; no spurious change. |
| EC-10 | A different organization's fuel logs, vehicles, or summary | Never visible in any response, including aggregate totals. |
| EC-11 | Uploading a receipt with an unsupported/empty file | `400`; the fuel log itself remains valid and queryable regardless of receipt state. |

---

## 6. Acceptance Criteria

- [ ] **AC-1:** Creating a fuel log with no prior history for that vehicle returns `cost_per_km: null` and `is_anomalous: false`.
- [ ] **AC-2:** Creating a second fuel log with a valid higher odometer reading returns a `cost_per_km` exactly equal to `total_cost / (odometer_reading - previous.odometer_reading)`.
- [ ] **AC-3:** Creating a fuel log with an odometer reading not greater than the vehicle's previous log returns a `400` and does not persist a row.
- [ ] **AC-4:** After creating a fuel log with a higher odometer reading, `GET /api/v1/vehicles/{id}` reflects the new `current_odometer`.
- [ ] **AC-5:** A fuel log with `cost_per_km` deviating more than 20% from the vehicle's trailing 3-month average is returned with `is_anomalous: true`; one within 20% is `false`.
- [ ] **AC-6:** Forcing a failure in the vehicle-odometer-update step (e.g. simulated DB error) results in neither the fuel log nor the odometer update being persisted.
- [ ] **AC-7:** `POST /fuel/{id}/receipt` stores the file and returns `upload_status: pending`, with no `parsed_data` populated.
- [ ] **AC-8:** `PUT /fuel/{id}` changing `odometer_reading` recalculates `cost_per_km` correctly and does not alter any other fuel log's stored `cost_per_km`.
- [ ] **AC-9:** `GET /fuel/summary?month=YYYY-MM` returns totals matching a manual `SUM`/`AVG` over the same seeded data, both fleet-wide and per vehicle.
- [ ] **AC-10:** `GET /fuel` filtered by `vehicle_id`, `driver_id`, and a date range returns exactly the matching rows, scoped to the caller's organization.
- [ ] **AC-11:** No endpoint in this domain returns or is affected by another organization's data.
