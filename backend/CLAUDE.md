# CLAUDE.md — Backend Module

**Scope:** This file governs `backend/` only. It refines the root [`CLAUDE.md`](../CLAUDE.md) for this module; nothing here overrides the root directives (transparency logging in `prompts.md`, Pydantic v2, modular separation from `ai_agents`, etc.) — it makes them concrete for backend work.

**Source of truth for domain design:** [`backendPlan.md`](./backendPlan.md). That document is the reasoned derivation of every model, computation, and route below. When a change conflicts with this file, re-read `backendPlan.md` first — it explains *why*, not just *what*. Update both together if the design changes.

---

## The boundary principle (non-negotiable)

The backend computes only what is **deterministic and immediate**: arithmetic, comparisons, ratios, UNIONs, aggregations. It never guesses, forecasts, or interprets natural language.

- If a value can be computed the same way every time from its inputs (division, subtraction, threshold comparison, weighted average) → **backend**.
- If it requires inference, pattern recognition, forecasting, or NLP → **`ai_agents`**, via MCP tools that wrap backend endpoints or query the database read-only.

When implementing a feature from `backendPlan.md`, respect its `[MANUAL]` / `[COMPUTED]` / `[AI-FUTURE]` labels literally. Never implement an `[AI-FUTURE]` step in the backend "to save time" — it belongs in the decoupled `ai_agents` module and must be left as a clean extension point (a status field, a stored file, a queryable table) instead.

Concretely: the backend stores mechanic notes, diagnostic text, and uploaded documents **as-is**. It does not summarize, classify, extract keywords from, or vectorize them. That is `ai_agents`' job via Pinecone.

---

## Multi-tenancy and audit — apply to every domain model

Every domain model (everything except `Organization` and lookup-only tables) inherits both mixins defined in `backendPlan.md`:

```python
class AuditMixin:
    created_by: UUID       # FK -> User
    created_at: datetime   # server_default=now
    updated_by: UUID | None
    updated_at: datetime   # onupdate=now
    is_deleted: bool = False
    deleted_at: datetime | None

class OrgScopedMixin:
    organization_id: UUID  # FK -> Organization, indexed
```

Rules that follow from this, enforced in every service function without exception:

- **Every query filters by `organization_id` and `is_deleted=False`.** There is no cross-tenant query path. If a query needs to bypass this (rare, e.g. an internal admin job), name it explicitly (`_unscoped_...`) and justify it in a comment.
- **`created_by` is stamped from the JWT, never from client input.** The service layer sets it from the authenticated user's ID; it is not a field the request body can set.
- **Soft-delete only.** `DELETE` endpoints set `is_deleted=True` / `deleted_at=now()`. No `DELETE FROM` in application code, ever — this holds especially for Problem 4 accountability records (`DriverReport`, `IncidentLog`), where hard-delete would destroy the audit trail the whole domain exists to protect.

---

## Computed fields: write-time vs. read-time — pick deliberately

This is the single most important pattern in the domain layer and the plan draws the line precisely in each problem. Follow it exactly; getting this backwards silently breaks the product's core value proposition.

**Compute and freeze on write** when the value should reflect state *as it was at that moment*, even if inputs change later:
- `FuelLog.cost_per_km` — computed from the previous log's odometer delta, frozen at creation.
- `MaintenanceLog.next_due_km` / `next_due_date` — computed from `Vehicle.service_interval_km/months` at creation time. If the vehicle's intervals change later, existing logs keep their original values.
- `TripLog.distance_km`.

**Compute fresh on every read, never store** when the value drifts as time or mileage passes and a stored copy would go stale:
- Compliance status (`compliant` / `due_soon` / `overdue` / `never_performed`) — a vehicle compliant yesterday can be overdue today purely because mileage increased. There is no `compliance_status` column.
- `/maintenance/upcoming` and `/maintenance/overdue` — computed by comparing current `Vehicle.current_odometer` against stored `next_due_km` at query time.
- Fleet-health composite score (Problem 5).

When adding a new computed value, ask explicitly: *does this need to reflect history, or current state?* That answer decides write-time vs. read-time — don't default to one out of habit.

---

## Side effects belong in the same transaction, not a queue

Several endpoints mutate more than one table as part of one logical event (see `backendPlan.md` "Backend principles applied" sections for each problem). Examples:

- Creating a `FuelLog` also updates `Vehicle.current_odometer` and runs the 20%-deviation anomaly check.
- Creating a `MechanicReport` decrements `PartsInventory.qty_on_hand` for each `parts_used` entry and checks `reorder_threshold`.
- `PATCH /purchase-orders/{id}/receive` increments stock for every line item **and** recalculates `Supplier.reliability_score`.
- Creating a `TripLog` updates `Vehicle.current_odometer`.

All of these are one DB transaction, all-or-nothing. **Do not introduce background jobs, message queues, or async task runners for these.** At this scale, transactional consistency is strictly better than eventual consistency — this was a deliberate architectural choice in the plan, not an oversight to "fix" later. If a service function needs to touch two tables, it does so inside one `async with session.begin():` block (or equivalent), and if either write fails, both roll back.

Threshold/anomaly alerts (low stock, cost-per-km deviation) are **return values from the write endpoint**, not a notification system — the frontend reads a flag in the response. Don't build polling or webhook infrastructure for this.

---

## Directory conventions (this module)

```text
backend/
├── app/
│   ├── api/          # FastAPI routers — one file per domain (fuel.py, maintenance.py, compliance.py, inventory.py, suppliers.py, purchase_orders.py, trips.py, driver_reports.py, incidents.py, dashboard.py, documents.py, vehicles.py, drivers.py, auth.py)
│   ├── core/          # config.py, database.py, security.py — no domain logic here
│   ├── models/         # SQLAlchemy models — mixins.py holds AuditMixin/OrgScopedMixin, one file per domain otherwise
│   ├── schemas/       # Pydantic v2 request/response schemas, mirroring app/api/ file-for-file
│   └── services/       # All computation and side-effect logic lives here, never in routers
├── tests/               # pytest — one test module per router/service pair
└── alembic/             # migrations; one revision per model addition, never hand-edit an applied migration
```

**Routers stay thin.** A router function parses the request, calls one service function, and returns the response. Computation (`cost_per_km`, `next_due_km`, compliance comparisons, timeline UNIONs, reliability scoring) lives in `app/services/`, never inline in `app/api/`. This is what lets `ai_agents`' MCP tools and the dashboard aggregation endpoints reuse the same logic instead of duplicating queries (e.g. `/dashboard/summary` must call `FuelService.get_monthly_aggregation()`, not reimplement it).

**JSONB over join tables for line items / compatibility arrays** at this scale — `PurchaseOrder.line_items`, `PartsInventory.compatible_vehicles`, `MechanicReport.parts_used`, `FuelReceipt.parsed_data`, `Document.extracted_data`. This was an explicit tradeoff in the plan (query simplicity over normalization for dozens/hundreds of rows, not millions) — don't "fix" it into a normalized schema without discussing it first.

**Append-only models have no `PUT`/`PATCH` route.** `DriverReport` is the clearest case — no update endpoint exists at all, by design, to keep the accountability audit trail reliable. `IncidentLog` is a partial case: only resolution fields (`resolution_status`, `resolution_notes`) are updatable via `PUT`; `description` and `severity` are immutable after creation. Don't add a generic update endpoint to either without re-reading Problem 4 in `backendPlan.md`.

---

## Testing

Per the root directive, every new feature needs pytest coverage. For this module specifically:

- Any `[COMPUTED]` field needs a unit test asserting the exact formula (e.g. `cost_per_km`, `next_due_km`, `distance_km`, `reliability_score`) including the edge case of no prior record (first `FuelLog` for a vehicle → `cost_per_km` is `null`, not an error).
- Any multi-table side effect needs a transaction-rollback test: force the second write to fail and assert the first write did not persist.
- Compliance/overdue logic needs tests for all four states (`compliant`, `due_soon`, `overdue`, `never_performed`), since `never_performed` (no matching `MaintenanceLog` at all) is easy to miss with an inner join.
- Org-scoping needs a test per list/get endpoint confirming a second organization's rows never leak into results.

---

## Safety hook for agentic DB access

The root directive's `pre_tool_call` read-only SQL safety hook (for `ai_agents`' MCP database access) is implemented and tested in `ai_agents/tools/`, not here — but any MCP-facing endpoint or read-only service function this module exposes should assume it will be queried by an LLM-driven agent and must not require write access to serve a read. Keep read paths (dashboard aggregations, compliance status, timelines) free of side effects so they're safe to expose over MCP as-is.
