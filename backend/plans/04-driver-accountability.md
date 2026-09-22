# Plan 04 — Driver Accountability & Asset Misuse

**Problem source:** [`backendPlan.md`](../backendPlan.md#problem-4--driver-accountability--asset-misuse) § Problem 4
**Module conventions:** [`backend/CLAUDE.md`](../CLAUDE.md)

**One-line goal:** an auditable, append-only chronological trail — `TripLog` (custody window), `DriverReport` (handover condition, append-only), `IncidentLog` (what went wrong, with a resolution workflow) — interleaved via a single `UNION ALL` timeline query per vehicle and per driver.

---

## 0. Prerequisites

- **[`plans/00-foundation.md`](./00-foundation.md)** — `Vehicle.current_odometer`, `Driver` (with optional `user_id` link), mixins, `require_role`/`get_current_user`/`get_current_driver_profile`.
- No cross-dependency on Plans 02/03 — this domain is self-contained except for reading `Vehicle`/`Driver`.
- Row-level "own only" filtering in this plan uses `get_current_driver_profile` (Plan 00 §5) exactly as Plan 01 does for `FuelLog` — filter on `driver_id`, never on `created_by`, since a manager can log a trip/report on a driver's behalf.

---

## 1. Models — `app/models/accountability.py`

### `TripLog`

| Field | Type | Notes |
|---|---|---|
| `id` | `UUID` (pk) | |
| `driver_id` | `UUID` FK → `drivers.id` | |
| `vehicle_id` | `UUID` FK → `vehicles.id` | |
| `start_time` | `datetime` | |
| `end_time` | `datetime`, nullable | null while trip is in progress |
| `start_odometer` | `int` | |
| `end_odometer` | `int`, nullable | null while trip is in progress |
| `distance_km` | `int`, nullable | **computed at write-time**, only when `end_odometer` is set |
| `fuel_consumed` | `numeric(10,2)`, nullable | manual, optional |
| `notes` | `text`, nullable | |
| + `AuditMixin`, `OrgScopedMixin` | | |

### `DriverReport` — **append-only, no update route at all**

| Field | Type | Notes |
|---|---|---|
| `id` | `UUID` (pk) | |
| `driver_id` | `UUID` FK → `drivers.id` | |
| `vehicle_id` | `UUID` FK → `vehicles.id` | |
| `shift_date` | `date` | |
| `vehicle_condition` | `enum(good, fair, poor)` | |
| `handover_notes` | `text`, nullable | |
| `issues_reported` | `text`, nullable | |
| + `AuditMixin` (still gets `is_deleted`/soft-delete for moderation, but no update path), `OrgScopedMixin` | |

### `IncidentLog` — **immutable core fields, updatable resolution workflow**

| Field | Type | Notes |
|---|---|---|
| `id` | `UUID` (pk) | |
| `driver_id` | `UUID` FK → `drivers.id`, nullable | may be unknown at filing time |
| `vehicle_id` | `UUID` FK → `vehicles.id` | |
| `incident_type` | `enum(damage, violation, near_miss)` | **immutable after create** |
| `date` | `date` | **immutable after create** |
| `severity` | `enum(minor, moderate, severe, critical)` | **immutable after create** |
| `description` | `text` | **immutable after create** |
| `location_description` | `text`, nullable | **immutable after create** |
| `estimated_cost` | `numeric(12,2)`, nullable | **immutable after create** |
| `resolution_status` | `enum(open, investigating, resolved, closed)` default `open` | **updatable** |
| `resolution_notes` | `text`, nullable | **updatable**, set when moving to `resolved`/`closed` |
| + `AuditMixin`, `OrgScopedMixin` | | |

**Migration order:** all three can migrate independently (no FKs between them, only to `Vehicle`/`Driver`).

---

## 2. Schemas — `app/schemas/accountability.py`

- `TripLogCreate` — `driver_id, vehicle_id, start_time, end_time, start_odometer, end_odometer, fuel_consumed, notes`. `end_time`/`end_odometer` optional to support "start trip now, close it later" — but the plan describes trips as logged with both ends known; if the UI always submits both at once, make them required and skip the in-progress case entirely. **Decide this against actual frontend flow before implementing** rather than building unused optionality.
- `TripLogResponse` — full row + `distance_km`.
- `DriverReportCreate` — `driver_id, vehicle_id, shift_date, vehicle_condition, handover_notes, issues_reported`. **No `DriverReportUpdate` schema exists — do not create one.**
- `DriverReportResponse` — full row.
- `IncidentLogCreate` — `driver_id, vehicle_id, incident_type, date, severity, description, location_description, estimated_cost`.
- `IncidentLogResolutionUpdate` — **only** `resolution_status, resolution_notes`. Does not include `description`, `severity`, `incident_type`, etc. — this schema shape is what enforces immutability at the API boundary, not a service-layer check alone.
- `IncidentLogResponse` — full row.
- `TimelineEntry` — discriminated union: `{record_type: Literal["trip","report","incident"], date: datetime, id: UUID, summary: dict}` where `summary` holds type-specific fields (or use three optional sub-objects gated by `record_type`).
- `TimelineResponse` — `list[TimelineEntry]`.

---

## 3. Service layer

### 3.1 `app/services/trip_service.py`

```python
async def create_trip(db, org_id, data: TripLogCreate, created_by) -> TripLog:
    """
    1. distance_km = end_odometer - start_odometer if end_odometer is not None else None.
       Reject (400) if end_odometer is provided and < start_odometer.
    2. Insert TripLog.
    3. If end_odometer is not None and end_odometer > vehicle.current_odometer:
       update vehicle.current_odometer. Same pattern as FuelLog (Plan 01).
    4. Single transaction; roll back together.
    """
async def list_trips(db, org_id, driver_id=None, vehicle_id=None, date_from=None, date_to=None) -> list[TripLog]: ...
async def get_trip(db, org_id, trip_id) -> TripLog: ...
```

### 3.2 `app/services/driver_report_service.py`

```python
async def create_driver_report(db, org_id, data: DriverReportCreate, created_by) -> DriverReport:
    """Plain insert. No update function exists in this module -- if a future request asks
    for 'let drivers fix a typo in their report,' that is a product decision requiring
    re-reading backendPlan.md's accountability rationale first, not a quick addition here."""
async def list_driver_reports(db, org_id, driver_id=None, vehicle_id=None, condition=None) -> list[DriverReport]: ...
async def get_driver_report(db, org_id, report_id) -> DriverReport: ...
```

### 3.3 `app/services/incident_service.py`

```python
async def create_incident(db, org_id, data: IncidentLogCreate, created_by) -> IncidentLog: ...
async def update_incident_resolution(db, org_id, incident_id, data: IncidentLogResolutionUpdate, updated_by) -> IncidentLog:
    """Only touches resolution_status / resolution_notes -- enforced by the schema shape,
    but double-check the service function doesn't accept **data.dict() blindly against the
    ORM model in a way that would let extra fields slip through."""
async def list_incidents(db, org_id, incident_type=None, severity=None, resolution_status=None) -> list[IncidentLog]: ...
async def get_incident(db, org_id, incident_id) -> IncidentLog: ...
```

### 3.4 `app/services/timeline_service.py`

```python
async def get_vehicle_timeline(db, org_id, vehicle_id) -> list[TimelineEntry]:
    """
    Single SQL UNION ALL across trip_logs, driver_reports, incident_logs, each SELECT
    projecting a literal record_type discriminator column, filtered by vehicle_id and
    organization_id and is_deleted=False in each branch, ORDER BY date DESC applied to
    the union as a whole (not stitched in Python -- see CLAUDE.md 'Timeline as a UNION ALL
    query, not application-layer stitching').
    Use SQLAlchemy's `union_all()` on three `select()` statements with aligned column sets,
    or a raw SQL query if the ORM union ergonomics are too awkward for the discriminator.
    """
async def get_driver_timeline(db, org_id, driver_id) -> list[TimelineEntry]:
    """Same pattern, filtered by driver_id instead of vehicle_id."""
```

---

## 4. Routes

Per `plans/00-foundation.md` §6: `TripLog`/`DriverReport` are `admin: full`, `fleet_manager: read all`, `driver: own only`, `mechanic: —`. `IncidentLog` is **not listed in the matrix** — treated below per `backendPlan.md`'s narrative ("manager or driver logs an incident"), flagged as an inference to confirm, not a settled rule.

### `app/api/trips.py`

| Method | Path | Handler | Roles allowed | Row-level filter |
|---|---|---|---|---|
| POST | `/api/v1/trips` | `create_trip` | `admin`, `driver` | — |
| GET | `/api/v1/trips` | `list_trips` (filters: `driver_id`, `vehicle_id`, `date_from`, `date_to`) | `admin`, `fleet_manager`, `driver` | `driver` restricted to own `driver_id`, per `get_current_driver_profile` |
| GET | `/api/v1/trips/{id}` | `get_trip` | `admin`, `fleet_manager`, `driver` | same; `404` (not `403`) for another driver's trip |

`mechanic` has no access to this router.

### `app/api/driver_reports.py`

| Method | Path | Handler | Roles allowed | Row-level filter |
|---|---|---|---|---|
| POST | `/api/v1/driver-reports` | `create_driver_report` | `admin`, `driver` | — |
| GET | `/api/v1/driver-reports` | `list_driver_reports` (filters: `driver_id`, `vehicle_id`, `condition`) | `admin`, `fleet_manager`, `driver` | `driver` restricted to own `driver_id` |
| GET | `/api/v1/driver-reports/{id}` | `get_driver_report` | `admin`, `fleet_manager`, `driver` | same |

`mechanic` has no access to this router. **No `PUT`/`PATCH`/`DELETE` route in this router.** If a linter or scaffold generator auto-adds a CRUD update route, remove it — this is intentional per `backendPlan.md`.

### `app/api/incidents.py`

| Method | Path | Handler | Roles allowed (inferred — confirm) | Row-level filter |
|---|---|---|---|---|
| POST | `/api/v1/incidents` | `create_incident` | `admin`, `fleet_manager`, `driver` | — |
| GET | `/api/v1/incidents` | `list_incidents` (filters: `type`, `severity`, `status`) | `admin`, `fleet_manager`, `driver` | `driver` restricted to incidents where `driver_id` is their own, **or** incidents on vehicles they've driven — pick one and document it; the plan's source text doesn't specify which |
| GET | `/api/v1/incidents/{id}` | `get_incident` | `admin`, `fleet_manager`, `driver` | same |
| PUT | `/api/v1/incidents/{id}` | `update_incident_resolution` — body is `IncidentLogResolutionUpdate`, not a generic update schema | `admin`, `fleet_manager` only | resolution workflow is a manager/admin action, not a driver one |

`mechanic` has no access to this router (no stated role in the source material).

### Timeline endpoints — added to existing `vehicles.py` / `drivers.py` routers

| Method | Path | Handler | Roles allowed | Row-level filter |
|---|---|---|---|---|
| GET | `/api/v1/vehicles/{id}/timeline` | `timeline_service.get_vehicle_timeline` | all four roles (matches "Vehicles" row: everyone has at least read) | none — a vehicle's timeline is visible to anyone who can read that vehicle |
| GET | `/api/v1/drivers/{id}/timeline` | `timeline_service.get_driver_timeline` | `admin`, `fleet_manager`, `driver` | `driver` may only request **their own** `{id}` — a driver requesting another driver's timeline gets `403`/`404`, since this view exposes another person's handover/incident history, not just vehicle state |

---

## 5. Tests

- `test_distance_computed_on_create` — exact `end_odometer - start_odometer`.
- `test_vehicle_odometer_updated_as_side_effect` (mirrors Plan 01's fuel test).
- `test_trip_rejects_end_odometer_less_than_start`.
- `test_driver_report_has_no_update_route` — assert `PUT`/`PATCH` on `/driver-reports/{id}` returns 405, not just "we didn't write a handler."
- `test_driver_report_append_only_in_service_layer` — no function in `driver_report_service.py` mutates an existing row; a static/introspection check or simply the absence of an update function.
- `test_incident_resolution_update_ignores_immutable_fields` — send `description`/`severity` in the resolution-update request body, assert they're rejected by schema validation (extra fields forbidden) or silently ignored **and** unchanged in the DB — pick one behavior and test it explicitly.
- `test_incident_original_fields_immutable_after_create` — attempt to change `description` via any code path, assert failure.
- `test_soft_delete_recoverable` — soft-deleted `IncidentLog`/`DriverReport`/`TripLog` rows are excluded from list/get but still present in the table with `is_deleted=True`.
- `test_timeline_interleaves_and_orders_correctly` — seed one of each record type with distinct dates, assert the returned order and `record_type` discriminators.
- `test_timeline_same_date_ordering` — two records sharing the exact same `date`/timestamp still return deterministically (add a stable secondary sort key, e.g. `id` or `created_at`).
- `test_timeline_scoped_to_single_vehicle_or_driver` — records for other vehicles/drivers never appear.
- `test_created_by_stamped_on_every_record` — across all three models, `created_by` matches the authenticated user, not a client-supplied value.
- `test_org_scoping` across all four routers (trips, driver-reports, incidents, timelines).
- `test_mechanic_forbidden_on_all_routes` — `mechanic` tokens get `403` across trips, driver-reports, and incidents routers.
- `test_driver_own_only_filter_on_trips_and_reports` — two drivers seeded in one org, each sees only their own `TripLog`/`DriverReport` rows.
- `test_driver_cannot_view_another_drivers_timeline` — `GET /drivers/{other_id}/timeline` as a `driver` token returns `403`/`404`.
- `test_fleet_manager_cannot_resolve_incidents_as_driver_would` — actually confirm the reverse: `driver` token on `PUT /incidents/{id}` gets `403` (resolution is manager/admin only per the inferred rule above).

---

## 6. Explicit non-goals

- Driver risk scoring from incident frequency/severity — `ai_agents` `DriverRisk` agent.
- Semantic search over `IncidentLog.description` for recurring language patterns ("brakes felt soft") — RAG via Pinecone, not backend.

Do not add a `risk_score` column to `Driver` in this plan.
