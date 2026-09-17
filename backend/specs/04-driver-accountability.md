# Spec 04 — Driver Accountability & Asset Misuse

**Derived from:** [`backendPlan.md`](../backendPlan.md#problem-4--driver-accountability--asset-misuse) · [`plans/04-driver-accountability.md`](../plans/04-driver-accountability.md)
**Status:** Ready for execution
**Depends on:** [`specs/00-foundation.md`](./00-foundation.md) — `Vehicle`, `Driver`, `AuditMixin`/`OrgScopedMixin`, `require_role`/`get_current_driver_profile`. No cross-dependency on Specs 02/03. **`IncidentLog` role access is inferred, not matrix-specified** — see Constraints §4.8.

---

## 1. Problem Statement

A truck returns with a dented fender. The driver who returned it says it was already damaged; the driver before them says the same. There is no record of vehicle condition at each handover, so responsibility is unassignable. Separately, a driver is consistently late — but without timestamped trip records, that's an impression, not evidence. The fleet has no auditable trail linking *who had the vehicle, when,* and *what state it was in* at each point in that custody chain.

---

## 2. Functional Requirements

| ID | Requirement |
|---|---|
| FR-4.1 | The system shall allow a driver to log a trip: vehicle, driver, start time, end time, start odometer, end odometer, optional fuel consumed, optional notes. |
| FR-4.2 | On creation, the system shall compute `distance_km = end_odometer - start_odometer` when both odometer values are present. |
| FR-4.3 | On creation, the system shall update `Vehicle.current_odometer` if `end_odometer` exceeds the currently stored value. |
| FR-4.4 | The system shall allow a driver to submit a handover report at end of shift: vehicle condition (`good`/`fair`/`poor`), handover notes, issues reported. |
| FR-4.5 | Handover reports shall be **append-only** — the system shall provide no update or delete endpoint for them once created. |
| FR-4.6 | The system shall allow filing an incident: type (`damage`/`violation`/`near_miss`), severity (`minor`/`moderate`/`severe`/`critical`), description, location, estimated cost. |
| FR-4.7 | Incident core fields (type, severity, description, location, cost, date) shall be immutable after creation; only `resolution_status` and `resolution_notes` shall be editable, via a workflow (`open → investigating → resolved → closed`). |
| FR-4.8 | The system shall expose a chronologically ordered timeline per vehicle, interleaving trips, handover reports, and incidents with a type discriminator. |
| FR-4.9 | The system shall expose the same timeline view per driver. |
| FR-4.10 | The system shall never delete accountability records — deletion is soft-delete only, and no record is ever permanently destroyed by application code. |
| FR-4.11 | The system shall never compute driver risk scores or search incident text for recurring patterns — out of scope for this module. |

---

## 3. Behaviour

### 3.1 Create trip (`POST /api/v1/trips`)

1. If `end_odometer` is provided: `distance_km = end_odometer - start_odometer`. If `end_odometer < start_odometer`, reject (`400`).
2. If `end_odometer` is absent, `distance_km = null` (trip in progress, if the product supports open-ended trips — confirm against the actual frontend flow before building this branch; otherwise require both timestamps/odometers at creation).
3. Insert the trip.
4. If `end_odometer` is present and exceeds `Vehicle.current_odometer`, update it in the same transaction as step 3.
5. Commit atomically.

### 3.2 Create handover report (`POST /api/v1/driver-reports`)

1. Plain insert — `driver_id, vehicle_id, shift_date, vehicle_condition, handover_notes, issues_reported`, plus server-stamped `created_by`.
2. No corresponding update function exists anywhere in the service layer. This is not an oversight — it is the mechanism that makes the audit trail trustworthy.

### 3.3 File / update incident (`POST /api/v1/incidents`, `PUT /api/v1/incidents/{id}`)

1. `POST` inserts all fields as submitted, with `resolution_status` defaulting to `open`.
2. `PUT` accepts **only** `resolution_status` and `resolution_notes` in its request schema — the schema shape itself is what prevents tampering with `description`/`severity`/etc., not just a service-layer check.
3. Any attempt to change an immutable field via `PUT` is either rejected by schema validation (extra/unknown fields forbidden) or silently ignored, per one documented, tested choice.

### 3.4 Timeline (`GET /vehicles/{id}/timeline`, `GET /drivers/{id}/timeline`)

1. A single SQL `UNION ALL` across `trip_logs`, `driver_reports`, `incident_logs`, each branch projecting a literal `record_type` discriminator (`trip`/`report`/`incident`) and filtered by the target vehicle/driver, `organization_id`, and `is_deleted = false`.
2. The union result is ordered by date descending, with a stable secondary sort (e.g. `created_at` or `id`) to guarantee deterministic ordering for same-timestamp records.
3. Ordering and interleaving happen entirely in SQL — never stitched together from three separate application-layer queries.

---

## 4. Constraints

1. **Organization scoping** on every model and query.
2. **Append-only for `DriverReport`.** No `PUT`/`PATCH`/`DELETE` route exists for it; the service layer contains no function that mutates an existing row.
3. **Partial immutability for `IncidentLog`.** Original fields are frozen at creation; only the resolution workflow fields are ever writable afterward.
4. **Soft-delete everywhere in this domain, hard-delete nowhere.** `is_deleted=True` hides a record from normal queries but never destroys it — an incident can never be made to disappear as evidence.
5. **Timeline is one UNION ALL query**, not three queries merged in Python — this is both a performance and a correctness requirement (guarantees consistent ordering across same-date records from different tables).
6. **`created_by` is stamped server-side** on every record from the authenticated user — no record can exist without a known author.
7. **Odometer updates from trip logging follow the same non-decreasing rule** as fuel logging (Spec 01) — never regress `Vehicle.current_odometer`.
8. **Access control per the Spec 00 permission matrix:** `TripLog`/`DriverReport` are `admin: full`, `fleet_manager: read all`, `driver: own only`, `mechanic: none`. `IncidentLog` is **not in the matrix** — this spec infers `admin`/`fleet_manager`/`driver` can create and read (matching the "manager or driver logs an incident" narrative in `backendPlan.md`), with resolution updates (`PUT`) restricted to `admin`/`fleet_manager` only. **Confirm this inference before treating it as final** — it is a gap in the source plan, not a documented rule.
9. **Row-level "own only" filtering uses `Driver.id` via `get_current_driver_profile`, never `created_by`.** A fleet manager or admin logging a trip/report on a driver's behalf produces a record whose `created_by` (the acting `User`) differs from `driver_id` (whose custody/condition it's about) — the ownership filter is always on `driver_id`.
10. **A `driver`-role caller may only request their own `/drivers/{id}/timeline`.** Unlike the vehicle timeline (visible to all authenticated roles, since it's about the asset, not a person), the driver timeline exposes another individual's handover/incident history and is access-restricted accordingly.

---

## 5. Edge Cases and Error Handling

| # | Scenario | Expected behavior |
|---|---|---|
| EC-1 | `end_odometer < start_odometer` on trip creation | `400`; no row inserted, vehicle odometer untouched. |
| EC-2 | Trip created without `end_time`/`end_odometer` (in-progress trip), if this mode is supported | `distance_km = null`; vehicle odometer unaffected by this trip until it's later completed via a separate update path (define explicitly if in-progress trips are in scope — otherwise disallow this case entirely at the schema level). |
| EC-3 | Attempt to `PUT`/`PATCH`/`DELETE` a `DriverReport` | `405 Method Not Allowed` — no route exists. |
| EC-4 | `PUT /incidents/{id}` request body includes `description` or `severity` | Rejected by schema validation, or accepted-but-ignored — whichever is chosen must be the single tested, documented behavior; the field must not change in the database either way. |
| EC-5 | `PUT /incidents/{id}` transitions `resolution_status` from `closed` back to `open` | Allowed unless the product explicitly forbids re-opening — default to allowing it (fleet managers do reopen closed incidents) unless told otherwise. |
| EC-6 | Two timeline entries (e.g. a trip and a report) share the exact same date/timestamp | Deterministic, stable ordering via the documented secondary sort key — not database-dependent, undefined ordering. |
| EC-7 | A vehicle or driver with zero records in any of the three tables | Timeline endpoint returns an empty list, not an error. |
| EC-8 | Soft-deleted record queried via timeline or list endpoints | Excluded from results, but still present in the underlying table (verifiable directly, not via the API). |
| EC-9 | `driver_id` on an incident is unknown/unassigned at filing time | Allowed — `driver_id` is nullable on `IncidentLog`. |
| EC-10 | Cross-organization access to trips, reports, incidents, or timelines | Never visible. |
| EC-11 | `mechanic` calls any route in this domain | `403` — matrix grants `mechanic` no access to trips, reports, or incidents. |
| EC-12 | `driver` requests `GET /trips`/`GET /driver-reports` | Returns only rows where `driver_id` matches their own linked `Driver` profile; empty list if unlinked. |
| EC-13 | `driver` requests `GET /drivers/{other_driver_id}/timeline` | `403`/`404` — a driver may only view their own timeline. |
| EC-14 | `driver` attempts `PUT /incidents/{id}` (resolution update) | `403` per the inferred rule that resolution is a manager/admin action. |

---

## 6. Acceptance Criteria

- [ ] **AC-1:** Creating a trip with valid odometer readings returns `distance_km = end_odometer - start_odometer`.
- [ ] **AC-2:** Creating a trip with `end_odometer < start_odometer` fails with `400` and persists nothing.
- [ ] **AC-3:** After a trip completes with a higher `end_odometer`, `Vehicle.current_odometer` reflects it.
- [ ] **AC-4:** No route responds to `PUT`, `PATCH`, or `DELETE` on `/driver-reports/{id}` with anything other than `405`/`404` (method not implemented).
- [ ] **AC-5:** `PUT /incidents/{id}` successfully updates `resolution_status`/`resolution_notes` while leaving `description`, `severity`, `incident_type`, `date`, `estimated_cost` unchanged, even when a request attempts to send them.
- [ ] **AC-6:** `GET /vehicles/{id}/timeline` returns trips, reports, and incidents for that vehicle interleaved in correct date-descending order, each tagged with the right `record_type`.
- [ ] **AC-7:** `GET /drivers/{id}/timeline` returns the analogous result scoped to a driver.
- [ ] **AC-8:** Two records sharing an identical timestamp are returned in a stable, repeatable order across repeated calls.
- [ ] **AC-9:** A soft-deleted trip, report, or incident is excluded from both list endpoints and the timeline, but remains present in the database with `is_deleted = true`.
- [ ] **AC-10:** Every created record's `created_by` matches the authenticated caller, regardless of any `created_by` value sent in the request body.
- [ ] **AC-11:** No cross-organization data appears in any endpoint in this domain.
- [ ] **AC-12:** `mechanic` tokens receive `403` on every route in trips, driver-reports, and incidents routers.
- [ ] **AC-13:** Two drivers seeded in the same organization each see only their own rows via `GET /trips` and `GET /driver-reports`; neither sees the other's.
- [ ] **AC-14:** A `driver` token requesting `GET /drivers/{other_id}/timeline` for a different driver is rejected; requesting their own succeeds.
- [ ] **AC-15:** A `driver` token calling `PUT /incidents/{id}` is rejected with `403`.
