# Plan 01 — Fuel Price Volatility

**Problem source:** [`backendPlan.md`](../backendPlan.md#problem-1--fuel-price-volatility) § Problem 1
**Module conventions:** [`backend/CLAUDE.md`](../CLAUDE.md)

**One-line goal:** turn every fill-up into a frozen `cost_per_km` data point, keep `Vehicle.current_odometer` current as a side effect, and flag fill-ups that deviate >20% from the vehicle's 3-month rolling average — all synchronously, all in one transaction.

---

## 0. Prerequisites

**[`plans/00-foundation.md`](./00-foundation.md) must be built first.** This plan assumes it's in place:

- `Organization`, `User` (auth-only), `Driver` (operational profile, optionally linked to `User` via nullable `user_id`)
- `Vehicle` (needs `current_odometer`, `organization_id`)
- `AuditMixin`, `OrgScopedMixin` in `app/models/mixins.py`
- `get_current_user`, `require_role(...)`, `get_current_driver_profile` in `app/core/deps.py`

Note the `User`/`Driver` split: `FuelLog.driver_id` FKs to `Driver.id`, never to `User.id`. `created_by` (from `AuditMixin`) is always a `User.id` — the account that made the API call — which is a different value from `driver_id` when, e.g., a fleet manager logs a fill-up on a driver's behalf.

---

## 1. Models — `app/models/fuel.py`

### `FuelLog`

| Field | Type | Notes |
|---|---|---|
| `id` | `UUID` (pk) | |
| `vehicle_id` | `UUID` FK → `vehicles.id` | indexed |
| `driver_id` | `UUID` FK → `drivers.id`, nullable | |
| `date` | `date` | required |
| `odometer_reading` | `int` | required, the reading at this fill-up |
| `liters_filled` | `numeric(10,2)` | required |
| `price_per_liter` | `numeric(10,2)` | required |
| `total_cost` | `numeric(12,2)` | required |
| `cost_per_km` | `numeric(10,4)`, nullable | **computed at write-time**, null on first fill-up for a vehicle |
| `is_anomalous` | `bool` default `False` | **computed at write-time** |
| `notes` | `text`, nullable | |
| + `AuditMixin`, `OrgScopedMixin` | | |

### `FuelReceipt`

| Field | Type | Notes |
|---|---|---|
| `id` | `UUID` (pk) | |
| `fuel_log_id` | `UUID` FK → `fuel_logs.id`, unique | one receipt per log |
| `file_path` | `str` | storage path/key, not the file itself |
| `file_type` | `str` | mime type |
| `upload_status` | `enum(pending, parsed, failed)` default `pending` | AI module flips this later — backend never sets it to `parsed` |
| `parsed_data` | `JSONB`, nullable | written only by `ai_agents`, backend never reads/writes structured content into it |
| + `AuditMixin`, `OrgScopedMixin` | | |

**Migration order:** `fuel_logs` before `fuel_receipts` (FK dependency). One alembic revision per table, or both in one revision if added together — keep consistent with how Tier 2 models were migrated.

---

## 2. Schemas — `app/schemas/fuel.py`

- `FuelLogCreate` — `vehicle_id, driver_id, date, odometer_reading, liters_filled, price_per_liter, total_cost, notes`. **Does not accept `cost_per_km` or `is_anomalous`** — server-computed only, reject if present or silently ignore via `model_config = {"extra": "forbid"}` on write-only computed fields.
- `FuelLogUpdate` — same fields, all optional (partial update). Recomputation rules in §4.
- `FuelLogResponse` — all `FuelLogCreate` fields + `id, cost_per_km, is_anomalous, created_at, receipt` (nested `FuelReceiptResponse | None`).
- `FuelReceiptResponse` — `id, file_path, file_type, upload_status, parsed_data`.
- `FuelSummaryResponse` — `{ month: str, total_cost: Decimal, avg_cost_per_km: Decimal | None, by_vehicle: list[{vehicle_id, total_cost, avg_cost_per_km}] }`.

All request/response models are Pydantic v2 (`ConfigDict`, not class-based `Config`), per root `CLAUDE.md`.

---

## 3. Service layer — `app/services/fuel_service.py`

Router functions call these; no computation in `app/api/fuel.py`.

```python
async def create_fuel_log(db: AsyncSession, org_id: UUID, data: FuelLogCreate, created_by: UUID) -> FuelLog:
    """
    Single transaction:
      1. Fetch the vehicle (org-scoped, is_deleted=False) — 404 if missing.
      2. Fetch the most recent prior FuelLog for this vehicle (by date/odometer, org-scoped).
      3. If a prior log exists: cost_per_km = total_cost / (odometer_reading - prior.odometer_reading).
         - Guard: if delta <= 0, raise a validation error (odometer must increase) rather than
           dividing by zero or storing a negative cost_per_km.
         - If no prior log: cost_per_km = None.
      4. Compute the vehicle's 3-month rolling average cost_per_km (across prior FuelLogs,
         excluding nulls). If |cost_per_km - rolling_avg| / rolling_avg > 0.20 -> is_anomalous = True.
         No rolling average yet (fewer than N prior points) -> is_anomalous = False, never flag
         on insufficient history.
      5. Insert the FuelLog row with computed fields frozen.
      6. If odometer_reading > vehicle.current_odometer: update vehicle.current_odometer.
      7. Commit. Roll back everything on any failure (steps 5+6 are one transaction).
    """

async def update_fuel_log(db, org_id, fuel_log_id, data: FuelLogUpdate, updated_by) -> FuelLog:
    """
    Recalculates cost_per_km using the same neighbor-lookup logic as create, because editing
    odometer_reading or total_cost changes the delta. Does NOT retroactively recompute
    cost_per_km on the *next* chronological FuelLog even though its "previous" value just
    changed -- see 'Known limitation' below. Does not re-run anomaly detection against logs
    created after this one.
    """

async def get_fuel_log(db, org_id, fuel_log_id) -> FuelLog: ...
async def list_fuel_logs(db, org_id, vehicle_id=None, driver_id=None, date_from=None, date_to=None, page, page_size) -> Page[FuelLog]: ...

async def attach_receipt(db, org_id, fuel_log_id, file, uploaded_by) -> FuelReceipt:
    """Stores the file via the configured storage backend, inserts FuelReceipt with
    upload_status='pending'. Does not parse the file."""

async def get_monthly_summary(db, org_id, month: date | None) -> FuelSummaryResponse:
    """Read-only aggregation: SUM(total_cost), AVG(cost_per_km) grouped by month and by vehicle.
    Reused directly by the Problem 5 dashboard service — do not duplicate this query there."""
```

**Known limitation to document in code, not silently fix:** editing a historical `FuelLog`'s odometer reading does not cascade-recompute `cost_per_km` on the chronologically-next log. Per `backendPlan.md` §"Computed fields on create, not on read," computed values are frozen at creation time by design — this is consistent with that principle, not a bug, but it must be a one-line comment at the top of `update_fuel_log` so it isn't "fixed" into a cascading recompute later.

---

## 4. Routes — `app/api/fuel.py`

Per `plans/00-foundation.md` §6 permission matrix: `FuelLog` is `admin: full`, `fleet_manager: read all`, `driver: own only`, `mechanic: —`.

| Method | Path | Handler | Roles allowed | Row-level filter |
|---|---|---|---|---|
| POST | `/api/v1/fuel` | `create_fuel_log` | `admin`, `driver` | — |
| GET | `/api/v1/fuel` | `list_fuel_logs` (filters: `vehicle_id`, `driver_id`, `date_from`, `date_to`) | `admin`, `fleet_manager`, `driver` | `driver` sees only rows where `driver_id == get_current_driver_profile().id` |
| GET | `/api/v1/fuel/{id}` | `get_fuel_log` | `admin`, `fleet_manager`, `driver` | same as above; `driver` gets `404` (not `403`, to avoid confirming another driver's log exists) for a log that isn't theirs |
| PUT | `/api/v1/fuel/{id}` | `update_fuel_log` | `admin`, `driver` | `driver` may only update their own log (same filter, applied before the update, not after) |
| POST | `/api/v1/fuel/{id}/receipt` | `attach_receipt` (multipart) | `admin`, `driver` | same ownership filter |
| GET | `/api/v1/fuel/summary` | `get_monthly_summary` (query: `month`) | `admin`, `fleet_manager` | fleet-wide, no row filter |
| `mechanic` | — | — | no access to any route in this domain (`require_role` excludes it entirely) | |

**Open item, per `plans/00-foundation.md` §6:** the matrix gives `fleet_manager` only `read all` on `FuelLog`, so `POST`/`PUT`/`receipt` exclude it above — this reads as intentional (fleet managers oversee, drivers/admins record), but confirm before implementation if fleet managers are expected to log fuel on a driver's behalf.

Every handler resolves `organization_id` from the JWT-derived `current_user`, never from a request parameter.

---

## 5. Tests — `tests/test_fuel.py`, `tests/test_fuel_service.py`

- `test_first_fuel_log_has_null_cost_per_km` — no prior log → `cost_per_km is None`, `is_anomalous is False`.
- `test_cost_per_km_computed_correctly` — two logs, assert exact division result.
- `test_odometer_not_increased_raises_validation_error` — second log's odometer ≤ first's.
- `test_vehicle_odometer_updated_as_side_effect` — after create, `Vehicle.current_odometer` reflects the new reading.
- `test_vehicle_odometer_not_decreased` — a lower odometer reading does not overwrite a higher stored value.
- `test_anomaly_flagged_over_20_percent_deviation` — seed 3 months of stable cost_per_km, insert an outlier, assert `is_anomalous is True`.
- `test_anomaly_not_flagged_with_insufficient_history` — fewer than the minimum rolling-average window → never flagged.
- `test_transaction_rollback_on_vehicle_update_failure` — force the odometer update to fail, assert the `FuelLog` row was not persisted either.
- `test_receipt_upload_sets_pending_status` — and does not populate `parsed_data`.
- `test_monthly_summary_matches_manual_aggregation` — cross-check `get_monthly_summary` against a hand-computed SUM/AVG over seeded rows.
- `test_org_scoping` — a second organization's fuel logs never appear in list/get/summary results.

---

## 6. Explicit non-goals (belongs to `ai_agents`, not this plan)

- Parsing `FuelReceipt` files into `parsed_data` (OCR/LLM extraction).
- Forecasting next month's fuel budget from trend data.
- Cross-referencing anomalies with `MechanicReport` text via RAG.

Do not build stubs or TODOs for these inside `app/services/fuel_service.py` — the AI module consumes this data via MCP tools that call the same read endpoints listed above.
