# Plan 03 — Breakdowns, Maintenance & Compliance (merged)

**Problem source:** [`backendPlan.md`](../backendPlan.md#problem-3--breakdowns-maintenance--compliance-merged) § Problem 3
**Module conventions:** [`backend/CLAUDE.md`](../CLAUDE.md)

**One-line goal:** `ComplianceRule` defines what's needed (by make/model), `MaintenanceLog` records what's been done (with `next_due_km`/`next_due_date` frozen at write-time), and the compliance checker compares the two **fresh on every read** — never stored, never stale. `MechanicReport` holds the unstructured diagnostic text as a separate 1:1 child, stored as-is for the AI module.

---

## 0. Prerequisites

- Foundation models + mixins.
- `Vehicle` must already have `make`, `model`, `current_odometer`, `service_interval_km`, `service_interval_months` fields — verify these exist on the Tier 2 `Vehicle` model before starting; add them via migration if missing.
- **Cross-dependency with Plan 02:** `MechanicReport.parts_used` triggers `inventory_service.decrement_stock_for_parts_used` (Plan 02 §3.2). Build `PartsInventory` at least minimally (or stub the decrement call behind a feature check) before wiring the mechanic-report endpoint fully. See Plan 02 §0 for suggested sequencing.

---

## 1. Models — `app/models/maintenance.py`

### `ComplianceRule`

| Field | Type | Notes |
|---|---|---|
| `id` | `UUID` (pk) | |
| `vehicle_make` | `str` | part of composite lookup key |
| `vehicle_model` | `str` | part of composite lookup key |
| `service_type` | `enum` (shared `ServiceType` enum, see below) | part of composite lookup key |
| `interval_km` | `int` | |
| `interval_months` | `int` | |
| `description` | `text`, nullable | |
| `source_document` | `str`, nullable | reference to a `Document` (manual PDF), not a FK — informational |
| + `AuditMixin`, `OrgScopedMixin` | | |
| Constraint | unique on `(organization_id, vehicle_make, vehicle_model, service_type)` — one rule per combination, per plan |

### `ServiceType` enum (shared by `ComplianceRule` and `MaintenanceLog`)

```python
class ServiceType(str, Enum):
    oil_change = "oil_change"
    brake_service = "brake_service"
    tire_rotation = "tire_rotation"
    engine_repair = "engine_repair"
    transmission = "transmission"
    electrical = "electrical"
    body_work = "body_work"
    general_inspection = "general_inspection"
    other = "other"
```

### `MaintenanceLog`

| Field | Type | Notes |
|---|---|---|
| `id` | `UUID` (pk) | |
| `vehicle_id` | `UUID` FK → `vehicles.id` | indexed |
| `date` | `date` | required |
| `odometer_at_service` | `int` | required |
| `service_type` | `ServiceType` | required |
| `description` | `text`, nullable | |
| `cost` | `numeric(12,2)`, nullable | |
| `mechanic_name` | `str`, nullable | free text, not necessarily a `User` FK |
| `next_due_km` | `int`, nullable | **computed at write-time**, frozen |
| `next_due_date` | `date`, nullable | **computed at write-time**, frozen |
| + `AuditMixin`, `OrgScopedMixin` | | |

### `MechanicReport`

| Field | Type | Notes |
|---|---|---|
| `id` | `UUID` (pk) | |
| `maintenance_log_id` | `UUID` FK → `maintenance_logs.id`, unique | 1:1 |
| `diagnostic_notes` | `text`, nullable | |
| `findings` | `text`, nullable | |
| `actions_taken` | `text`, nullable | |
| `parts_used` | `JSONB` | array of `{part_id, qty}` — triggers Plan 02 stock decrement |
| `recommendations` | `text`, nullable | |
| + `AuditMixin`, `OrgScopedMixin` | | |

**Migration order:** `compliance_rules` and `maintenance_logs` can migrate independently (no FK between them); `mechanic_reports` after `maintenance_logs`.

---

## 2. Schemas — `app/schemas/maintenance.py`, `app/schemas/compliance.py`

- `ComplianceRuleCreate` / `ComplianceRuleUpdate` (interval fields only) / `ComplianceRuleResponse`.
- `MaintenanceLogCreate` — `vehicle_id, date, odometer_at_service, service_type, description, cost, mechanic_name`. No `next_due_*` fields accepted.
- `MaintenanceLogUpdate` — same fields, partial; triggers recompute per §3 rules below.
- `MaintenanceLogResponse` — full row + `next_due_km, next_due_date` + nested `mechanic_report: MechanicReportResponse | None`.
- `MechanicReportCreate` — `diagnostic_notes, findings, actions_taken, parts_used: list[{part_id: UUID, qty: int}], recommendations`.
- `MechanicReportResponse` — full row + `low_stock_alerts: list[...]` echoed from the decrement call.
- `ComplianceStatusItem` — `{rule: ComplianceRuleResponse, status: Literal["compliant","due_soon","overdue","never_performed"], km_remaining: int | None, days_remaining: int | None, last_service_date: date | None}`.
- `VehicleComplianceResponse` — `{vehicle_id, items: list[ComplianceStatusItem]}`.
- `FleetComplianceMatrixResponse` — `list[VehicleComplianceResponse]`.
- `UpcomingMaintenanceItem` / `OverdueMaintenanceItem` — `{vehicle_id, plate_number, next_due_km, next_due_date, current_odometer, km_remaining}`.

---

## 3. Service layer

### 3.1 `app/services/maintenance_service.py`

```python
async def create_maintenance_log(db, org_id, data: MaintenanceLogCreate, created_by) -> MaintenanceLog:
    """
    1. Fetch vehicle (org-scoped) for service_interval_km / service_interval_months -- 404 if missing.
    2. next_due_km = odometer_at_service + vehicle.service_interval_km
       next_due_date = date + relativedelta(months=vehicle.service_interval_months)
       (both null if the vehicle has no interval configured for that dimension -- don't
       silently default to 0, which would make every log immediately overdue)
    3. Insert MaintenanceLog with next_due_* frozen. No vehicle-table side effect here
       (unlike FuelLog/TripLog, MaintenanceLog does not itself update current_odometer --
       odometer currency comes from fuel/trip logging, not maintenance logging; confirm this
       against backendPlan.md before changing -- it doesn't mention an odometer update here).
    """

async def update_maintenance_log(db, org_id, log_id, data: MaintenanceLogUpdate, updated_by) -> MaintenanceLog:
    """Recomputes next_due_km / next_due_date only if odometer_at_service or date changed,
    using the vehicle's *current* interval settings -- per backendPlan.md this is explicitly
    allowed on update (unlike FuelLog, there's no stated freeze-on-edit rule for maintenance)."""

async def get_maintenance_log(db, org_id, log_id) -> MaintenanceLog:
    """Eager-loads mechanic_report (per route spec: 'with mechanic report, eager loaded')."""

async def list_maintenance_logs(db, org_id, vehicle_id=None, service_type=None, date_from=None, date_to=None) -> list[MaintenanceLog]: ...

async def create_mechanic_report(db, org_id, log_id, data: MechanicReportCreate, created_by) -> tuple[MechanicReport, list[dict]]:
    """
    Single transaction:
      1. Fetch MaintenanceLog (org-scoped) -- 404 if missing. Reject if a MechanicReport
         already exists for this log (1:1 -- use POST-only, no upsert).
      2. Insert MechanicReport with parts_used stored as-is (JSONB) -- no parsing, no NLP.
      3. alerts = await inventory_service.decrement_stock_for_parts_used(db, org_id, data.parts_used)
      4. Commit. Roll back both the report insert and the stock decrement together on failure.
    Returns (report, alerts) so the router can include low_stock_alerts in the response.
    """

async def list_upcoming(db, org_id, window_km=1000) -> list[UpcomingMaintenanceItem]:
    """WHERE next_due_km IS NOT NULL AND (next_due_km - vehicle.current_odometer) < window_km
    AND (next_due_km - vehicle.current_odometer) >= 0. Read-time comparison, no stored flag."""

async def list_overdue(db, org_id) -> list[OverdueMaintenanceItem]:
    """WHERE vehicle.current_odometer > next_due_km OR today > next_due_date.
    Uses the *latest* MaintenanceLog per vehicle+service_type, not every log -- join against
    a subquery selecting MAX(date) per (vehicle_id, service_type) to avoid flagging a vehicle
    as overdue because of an old log that a newer one already superseded."""
```

### 3.2 `app/services/compliance_service.py`

```python
async def create_rule(db, org_id, data: ComplianceRuleCreate, created_by) -> ComplianceRule: ...
async def update_rule(db, org_id, rule_id, data, updated_by) -> ComplianceRule: ...
async def list_rules(db, org_id, vehicle_make=None, vehicle_model=None, service_type=None) -> list[ComplianceRule]: ...

async def get_vehicle_compliance(db, org_id, vehicle_id) -> VehicleComplianceResponse:
    """
    Read-only, computed fresh every call -- never stored:
      1. Fetch vehicle. Fetch all ComplianceRules where vehicle_make == vehicle.make
         AND vehicle_model == vehicle.model (org-scoped).
      2. For each rule:
         a. LEFT JOIN-equivalent: find the latest MaintenanceLog for this vehicle with
            service_type == rule.service_type (MAX(date), or None if no such log exists).
         b. If no MaintenanceLog -> status = 'never_performed' (treated as overdue),
            km_remaining = None, days_remaining = None.
         c. Else:
            km_gap = vehicle.current_odometer - last_service.odometer_at_service
            months_gap = (today - last_service.date) in months
            if km_gap > rule.interval_km or months_gap > rule.interval_months: 'overdue'
            elif km_gap > 0.8 * rule.interval_km or months_gap > 0.8 * rule.interval_months: 'due_soon'
            else: 'compliant'
            km_remaining = rule.interval_km - km_gap
            days_remaining = (interval as date) - today  # convert interval_months to days via last_service.date + relativedelta
      3. Return the list of ComplianceStatusItem, one per matching rule.
    """

async def get_fleet_compliance_matrix(db, org_id) -> FleetComplianceMatrixResponse:
    """Calls get_vehicle_compliance for every active vehicle in the org. For fleet sizes in
    the dozens this is fine as N sequential calls; if it becomes a bottleneck, batch the
    'latest MaintenanceLog per (vehicle, service_type)' query once for all vehicles instead
    of once per vehicle -- but don't pre-optimize this before it's measured."""
```

---

## 4. Routes

### `app/api/maintenance.py`

| Method | Path | Handler |
|---|---|---|
| POST | `/api/v1/maintenance` | `create_maintenance_log` |
| GET | `/api/v1/maintenance` | `list_maintenance_logs` (filters: `vehicle_id`, `service_type`, `date_from`, `date_to`) |
| GET | `/api/v1/maintenance/{id}` | `get_maintenance_log` |
| PUT | `/api/v1/maintenance/{id}` | `update_maintenance_log` |
| POST | `/api/v1/maintenance/{id}/mechanic-report` | `create_mechanic_report` |
| GET | `/api/v1/maintenance/upcoming` | `list_upcoming` |
| GET | `/api/v1/maintenance/overdue` | `list_overdue` |

### `app/api/compliance.py`

| Method | Path | Handler |
|---|---|---|
| POST | `/api/v1/compliance/rules` | `create_rule` |
| GET | `/api/v1/compliance/rules` | `list_rules` (filters: `make`, `model`, `service_type`) |
| PUT | `/api/v1/compliance/rules/{id}` | `update_rule` |
| GET | `/api/v1/compliance/status` | `get_fleet_compliance_matrix` |
| GET | `/api/v1/compliance/status/{vehicle_id}` | `get_vehicle_compliance` |

Also referenced from `app/api/vehicles.py`: `GET /api/v1/vehicles/{id}/compliance` should call the same `compliance_service.get_vehicle_compliance` — don't duplicate the logic in the vehicles router.

---

## 5. Tests

- `test_next_due_computed_on_create` — exact `next_due_km`/`next_due_date` arithmetic.
- `test_next_due_null_when_vehicle_has_no_interval_configured`.
- `test_next_due_recomputed_on_update_when_odometer_changes`.
- `test_next_due_not_recomputed_on_unrelated_update` (e.g. only `cost` changed).
- `test_mechanic_report_decrements_stock` — integration test spanning Plan 02, asserting the transaction is shared.
- `test_mechanic_report_rejects_duplicate` — second POST to the same `maintenance_log_id` fails.
- `test_upcoming_window_boundary` — exactly `999`, `1000`, `1001` km remaining.
- `test_overdue_by_km` / `test_overdue_by_date` / `test_overdue_uses_latest_log_only`.
- `test_compliance_status_compliant` / `_due_soon` / `_overdue` / `_never_performed` — all four states explicitly, since `never_performed` is the easiest to miss.
- `test_compliance_status_due_soon_boundary` — exactly at the 80% threshold.
- `test_compliance_fresh_on_every_read` — advance `vehicle.current_odometer` between two calls to the same endpoint and assert the status changes without any write to a compliance table.
- `test_rules_scoped_by_make_model_not_vehicle` — two vehicles of the same make/model share rule results; a third vehicle of a different model does not see them.
- `test_org_scoping` across both routers.

---

## 6. Explicit non-goals

- Semantic search / pattern detection over `MechanicReport.diagnostic_notes`/`findings` — `ai_agents` vectorizes these into Pinecone; backend only stores rich filter metadata (vehicle make, service_type, date — already available via the FK chain to `MaintenanceLog`/`Vehicle`).
- Extracting `ComplianceRule` entries automatically from uploaded manufacturer PDFs — `ai_agents` `ComplianceMonitor` agent, reading from `Document`.

Do not add NLP/classification logic to `create_mechanic_report`.
