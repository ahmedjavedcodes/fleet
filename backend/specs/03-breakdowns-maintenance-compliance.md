# Spec 03 — Breakdowns, Maintenance & Compliance (merged)

**Derived from:** [`backendPlan.md`](../backendPlan.md#problem-3--breakdowns-maintenance--compliance-merged) · [`plans/03-breakdowns-maintenance-compliance.md`](../plans/03-breakdowns-maintenance-compliance.md)
**Status:** Ready for execution
**Depends on:** Foundation models, including `Vehicle.make/model/current_odometer/service_interval_km/service_interval_months`. **Shares a transaction boundary with Spec 02** (mechanic report creation decrements parts stock).

---

## 1. Problem Statement

Two symptoms, one root cause. First: a fleet manager has 20 trucks at different mileages serviced at different times, tracked on paper or not at all — a timing belt goes unreplaced past its 80,000 km limit, snaps, and turns a ₹5,000 preventive fix into a ₹200,000 repair. Second: manufacturer maintenance guidelines exist in a drawer as PDFs; with vehicles from three manufacturers, nobody can manually check every vehicle against every rule, so violations pile up silently and warranty claims get rejected for missed service intervals. Both are the same question asked two ways — *given this vehicle's current mileage and last service date, is it due?* — and both need the same answer from the same data.

---

## 2. Functional Requirements

| ID | Requirement |
|---|---|
| FR-3.1 | The system shall allow defining a compliance rule per vehicle make + model + service type: interval in km, interval in months, description, optional source document reference. |
| FR-3.2 | Compliance rules shall apply to every vehicle sharing that make and model — no per-vehicle configuration. |
| FR-3.3 | The system shall allow recording a maintenance event: vehicle, date, odometer at service, service type (fixed enum), description, cost, mechanic name. |
| FR-3.4 | On creation, the system shall compute and freeze `next_due_km` and `next_due_date` from the vehicle's current service intervals. |
| FR-3.5 | The system shall allow attaching a diagnostic mechanic report (free-text notes, findings, actions taken, recommendations, and parts used) to a maintenance log, one report per log. |
| FR-3.6 | Attaching a mechanic report with `parts_used` shall trigger the inventory stock decrement defined in Spec 02, within the same transaction. |
| FR-3.7 | The system shall expose an "upcoming" list of vehicles within a configurable km window of their next due service. |
| FR-3.8 | The system shall expose an "overdue" list of vehicles past their next due km or next due date, based on the latest maintenance log per vehicle and service type. |
| FR-3.9 | The system shall compute, on every request, each vehicle's compliance status per applicable rule: `compliant`, `due_soon` (within 80% of either limit), `overdue`, or `never_performed` (no matching maintenance log exists at all). |
| FR-3.10 | The system shall expose both a per-vehicle compliance view and a fleet-wide compliance matrix. |
| FR-3.11 | The system shall never analyze, classify, or extract structured meaning from mechanic report free-text fields, and shall never auto-extract compliance rules from uploaded documents — both out of scope for this module. |

---

## 3. Behaviour

### 3.1 Create maintenance log (`POST /api/v1/maintenance`)

1. Load the vehicle (organization-scoped). Not found → `404`.
2. `next_due_km = odometer_at_service + vehicle.service_interval_km` (or `null` if the vehicle has no `service_interval_km` configured — never default to `0`, which would make the log immediately overdue).
3. `next_due_date = date + vehicle.service_interval_months` (same null-safety rule).
4. Insert the log with both computed fields frozen. This endpoint does **not** update `Vehicle.current_odometer` — odometer currency comes from fuel/trip logging (Specs 01/04), not maintenance logging.

### 3.2 Update maintenance log (`PUT /api/v1/maintenance/{id}`)

- Recomputes `next_due_km`/`next_due_date` **only if** `odometer_at_service` or `date` changed, using the vehicle's *current* interval settings. Unlike fuel logs, maintenance logs are allowed to reflect updated intervals on edit — this asymmetry is intentional per the source plan and must not be "fixed" into a frozen-forever rule without re-reading the plan.

### 3.3 Attach mechanic report (`POST /maintenance/{id}/mechanic-report`)

1. Load the maintenance log (organization-scoped). Not found → `404`.
2. Reject if a report already exists for this log (`409`) — 1:1, create-only, no upsert.
3. Insert the report with `parts_used` stored as-is (no parsing).
4. Call the Spec 02 stock-decrement function with `parts_used`, inside this same transaction.
5. Commit both the report insert and the stock decrement together; roll back both on any failure.
6. Return the report plus any `low_stock_alerts` from step 4.

### 3.4 Upcoming / overdue (`GET /maintenance/upcoming`, `GET /maintenance/overdue`)

- **Upcoming:** vehicles where `next_due_km is not null` and `0 <= (next_due_km - vehicle.current_odometer) < window_km` (default 1000). Computed at read time.
- **Overdue:** vehicles where `vehicle.current_odometer > next_due_km` or `today > next_due_date`, using only the **latest** maintenance log per `(vehicle, service_type)` — an old, already-superseded log must never cause a false overdue flag.

### 3.5 Compliance status (`GET /compliance/status/{vehicle_id}`, `GET /compliance/status`)

For each `ComplianceRule` matching the vehicle's make and model:

1. Find the latest `MaintenanceLog` for this vehicle with that rule's `service_type`.
2. No such log → status = `never_performed` (treated as overdue), `km_remaining`/`days_remaining` = `null`.
3. Otherwise:
   - `km_gap = vehicle.current_odometer - last_service.odometer_at_service`
   - `months_gap = today - last_service.date` (in months)
   - `km_gap > rule.interval_km` **or** `months_gap > rule.interval_months` → `overdue`
   - else `km_gap > 0.8 * rule.interval_km` **or** `months_gap > 0.8 * rule.interval_months` → `due_soon`
   - else → `compliant`
4. This is computed fresh on every call. No status is ever stored.

The fleet-wide matrix repeats this per active vehicle.

---

## 4. Constraints

1. **Organization scoping** on every model and query.
2. **`next_due_km`/`next_due_date` are write-time computations**, frozen at creation (and selectively recomputed on update per §3.2).
3. **Compliance status is always a read-time computation, never stored.** A vehicle compliant yesterday can be overdue today purely from accumulated mileage — there is no column that could drift stale.
4. **Absence of data is itself a violation.** A service type with no matching maintenance log is `never_performed`/overdue, not silently skipped. Queries must handle this as a left-join-with-null case, not an inner join that would drop the rule entirely.
5. **Rules are scoped by make/model, never by individual vehicle.** Adding a new vehicle of an existing make/model automatically inherits all its rules with zero configuration.
6. **Structured (`MaintenanceLog`) and unstructured (`MechanicReport`) data live in separate models.** SQL-queryable fields never mix with large free-text fields in the same table.
7. **Mechanic-report text is stored verbatim.** No keyword extraction, no classification, no severity scoring in this module.
8. **The mechanic-report + stock-decrement side effect is one transaction**, shared with Spec 02 — see that spec's constraints for the stock-specific rules.
9. **`ServiceType` is a fixed enum** shared identically between `ComplianceRule` and `MaintenanceLog` — the same nine values in both places, never diverging.

---

## 5. Edge Cases and Error Handling

| # | Scenario | Expected behavior |
|---|---|---|
| EC-1 | Vehicle has no `service_interval_km` or `service_interval_months` configured | The corresponding `next_due_*` field is `null`; the log is still created successfully. |
| EC-2 | A maintenance log is created for a service type with no matching `ComplianceRule` for that vehicle's make/model | The log is created normally; it simply has nothing to compare against in the compliance checker (the rule set is empty for that type, not an error). |
| EC-3 | Multiple maintenance logs of the same service type exist for a vehicle | Compliance and overdue checks use only the **latest** one by date. |
| EC-4 | `POST /maintenance/{id}/mechanic-report` called twice for the same log | Second call returns `409`; no duplicate report, no double stock decrement. |
| EC-5 | Mechanic report's `parts_used` references an invalid or out-of-org part | The entire report creation fails and rolls back (propagated from Spec 02's EC-1). |
| EC-6 | Vehicle exactly at 80% of a rule's km or month limit | Classified as `due_soon`, not `compliant` (boundary is inclusive of `due_soon`). |
| EC-7 | Vehicle exactly at 100% of a rule's limit (`km_gap == interval_km`) | Classified as `overdue` only when strictly greater (`>`); confirm and test the exact boundary explicitly since the spec's `>` vs `>=` choice is easy to get backwards. |
| EC-8 | A vehicle's make/model matches zero `ComplianceRule` rows | `GET /compliance/status/{vehicle_id}` returns an empty list, not an error. |
| EC-9 | `GET /maintenance/upcoming` window boundary (exactly 1000 km remaining) | Excluded (`< window_km`, not `<=`) — verify against the exact operator chosen and test the boundary. |
| EC-10 | Vehicle with `current_odometer` below `odometer_at_service` of its own latest log (data entry error) | Should not crash; `km_gap` may be negative, which correctly evaluates to `compliant` (negative gap is never `> interval_km`). |
| EC-11 | Cross-organization access to rules, logs, reports, or compliance views | Never visible. |

---

## 6. Acceptance Criteria

- [ ] **AC-1:** Creating a maintenance log computes `next_due_km`/`next_due_date` exactly per the formulas in §3.1, and both are `null` when the vehicle has no configured interval.
- [ ] **AC-2:** Updating a log's `odometer_at_service` recomputes `next_due_km`; updating an unrelated field (e.g. `cost`) does not.
- [ ] **AC-3:** Attaching a mechanic report with `parts_used` decrements the referenced parts' stock in the same request/transaction as the report creation.
- [ ] **AC-4:** A second `POST` of a mechanic report to the same maintenance log is rejected with `409`.
- [ ] **AC-5:** `GET /maintenance/upcoming` returns exactly the vehicles within the configured km window, verified at the boundary.
- [ ] **AC-6:** `GET /maintenance/overdue` correctly ignores a superseded older log when a newer log of the same service type exists for the same vehicle.
- [ ] **AC-7:** `GET /compliance/status/{vehicle_id}` returns all four possible statuses correctly for seeded scenarios: `compliant`, `due_soon`, `overdue`, `never_performed`.
- [ ] **AC-8:** Advancing `Vehicle.current_odometer` between two calls to the compliance endpoint (with no new writes to any compliance table) changes the returned status — proving it's computed fresh, not cached.
- [ ] **AC-9:** Two vehicles sharing the same make/model both see the same set of applicable rules; a third vehicle of a different model does not see them.
- [ ] **AC-10:** `GET /vehicles/{id}/compliance` returns identical results to `GET /compliance/status/{vehicle_id}` for the same vehicle (same underlying function).
- [ ] **AC-11:** No cross-organization data appears in any maintenance or compliance response.
