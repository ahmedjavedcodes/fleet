# Plan 05 — Strategic Insights

**Problem source:** [`backendPlan.md`](../backendPlan.md#problem-5--strategic-insights) § Problem 5
**Module conventions:** [`backend/CLAUDE.md`](../CLAUDE.md)

**One-line goal:** read-only aggregation endpoints under `/dashboard/` that assemble the numbers a fleet manager checks every morning, built entirely on top of existing service functions from Plans 01–04 — no new models, no new writes, and a composite per-vehicle health score for the AI module to consume later.

---

## 0. Prerequisites

**This plan must be built last.** It has a hard dependency on the service functions from every prior plan:

| Dependency | From | Used by |
|---|---|---|
| `fuel_service.get_monthly_summary` | Plan 01 | `dashboard/summary`, `dashboard/fuel-trends`, fleet-health fuel signal |
| `maintenance_service.list_overdue` | Plan 03 | `dashboard/summary`, `dashboard/maintenance-calendar`, fleet-health maintenance signal |
| `maintenance_service.list_upcoming` | Plan 03 | `dashboard/maintenance-calendar` |
| `compliance_service.get_vehicle_compliance` | Plan 03 | fleet-health compliance signal |
| `inventory_service.list_low_stock` | Plan 02 | `dashboard/summary` |
| `incident_service.list_incidents` | Plan 04 | `dashboard/summary`, fleet-health incident signal |
| `Vehicle`, `Driver` (active counts) | Plan 00 | `dashboard/summary` |
| `require_role` | Plan 00 | every route in this plan |

Do not start this plan until at least Plans 00, 01, 02, 03, and 04 have their service-layer functions in place (routers can lag, but the service functions must exist and be stable).

---

## 1. Models

**None.** This is the one problem in the plan that adds zero tables — confirmed by `backendPlan.md` §"Models and why each exists" for Problem 5. If implementation reveals a need for a stored table (e.g. to cache an expensive aggregation), treat that as a deviation from the plan requiring discussion first, not a default choice.

---

## 2. Schemas — `app/schemas/dashboard.py`

- `DashboardSummaryResponse`:
  ```python
  total_vehicles: int
  active_drivers: int
  month_fuel_cost: Decimal
  overdue_maintenance_count: int
  low_stock_parts_count: int
  open_incidents_count: int
  ```
- `FuelTrendPoint` — `{month: str, total_cost: Decimal, avg_cost_per_km: Decimal | None}`.
- `FuelTrendsResponse` — `list[FuelTrendPoint]` (last 12 months).
- `MaintenanceCalendarItem` — `{vehicle_id, plate_number, service_type, due_date: date, due_km: int | None, status: Literal["upcoming","overdue"]}`.
- `MaintenanceCalendarResponse` — `list[MaintenanceCalendarItem]` (next 30 days, upcoming + overdue merged).
- `VehicleHealthScore` — `{vehicle_id, plate_number, health_score: int, signals: {compliance: int, incidents: int, maintenance_currency: int, fuel_efficiency: int}}`.
- `FleetHealthResponse` — `list[VehicleHealthScore]`.

---

## 3. Service layer — `app/services/dashboard_service.py`

**Read-only. No function in this module ever opens a write transaction.**

```python
async def get_summary(db, org_id) -> DashboardSummaryResponse:
    """
    Composes, does not reimplement:
      total_vehicles       = count(Vehicle where status != 'retired', org-scoped)
      active_drivers        = count(Driver where status == 'active', org-scoped)
      month_fuel_cost        = fuel_service.get_monthly_summary(db, org_id, month=current_month).total_cost
      overdue_maintenance_count = len(await maintenance_service.list_overdue(db, org_id))
      low_stock_parts_count  = len(await inventory_service.list_low_stock(db, org_id))
      open_incidents_count   = count(IncidentLog where resolution_status in ('open','investigating'), org-scoped)
    """

async def get_fuel_trends(db, org_id, months=12) -> FuelTrendsResponse:
    """Calls fuel_service.get_monthly_summary once per of the last `months` months
    (or extend get_monthly_summary to accept a range and return all months in one query --
    prefer extending it over calling it 12 times, to avoid 12 round trips)."""

async def get_maintenance_calendar(db, org_id, window_days=30) -> MaintenanceCalendarResponse:
    """
    Merges maintenance_service.list_upcoming and list_overdue, filtered to next_due_date
    within window_days (upcoming ones) plus all currently-overdue ones regardless of how
    far past due -- an overdue item doesn't disappear from the calendar because it's
    'more than 30 days overdue.'
    """

async def get_fleet_health(db, org_id) -> FleetHealthResponse:
    """
    For each active vehicle:
      1. compliance signal: from compliance_service.get_vehicle_compliance -- normalize
         (compliant=100, due_soon=60, overdue=20, never_performed=0), average across all
         applicable rules for that vehicle. No applicable rules -> exclude this signal from
         the weighted average (not a 0 or 100 default).
      2. incidents signal: count IncidentLog in the last 90 days for this vehicle, map to
         0-100 via a defined bucket (0 incidents=100, 1=70, 2=40, 3+=10 -- pick concrete
         thresholds and document them here once decided, don't leave them implicit in code).
      3. maintenance currency signal: from maintenance_service overdue/upcoming state --
         not overdue and not due_soon=100, due_soon=60, overdue=10.
      4. fuel efficiency signal: trend of this vehicle's cost_per_km over the last 3 months
         vs. its own prior 3 months -- improving or flat=100, worsening moderately=60,
         worsening sharply (matches the >20% anomaly threshold from Plan 01)=20.
      5. health_score = weighted average of available signals. Define weights once
         (e.g. compliance 30%, incidents 25%, maintenance 25%, fuel 20%) and document them
         here -- this is a business decision, confirm the weighting with the user/PM before
         treating it as final, since backendPlan.md specifies the four signals but not their
         relative weights.
    """
```

**Every function here calls into an existing Plan 01–04 service function wherever one exists for the underlying number.** Do not write a second `SUM(total_cost) ... GROUP BY month` query for fuel trends when `fuel_service.get_monthly_summary` already does it — extend that function's signature (e.g. add a `months: int` range parameter) rather than duplicating its SQL here.

---

## 4. Routes — `app/api/dashboard.py`

Per `plans/00-foundation.md` §6: `Dashboard/insights` is `admin: full`, `fleet_manager: full`, `driver: —`, `mechanic: —`. All four routes below are gated identically — `require_role("admin", "fleet_manager")` — with no row-level filtering (the dashboard is inherently fleet-wide, not per-individual).

| Method | Path | Handler | Roles allowed |
|---|---|---|---|
| GET | `/api/v1/dashboard/summary` | `get_summary` | `admin`, `fleet_manager` |
| GET | `/api/v1/dashboard/fuel-trends` | `get_fuel_trends` (query: `months`, default 12) | `admin`, `fleet_manager` |
| GET | `/api/v1/dashboard/maintenance-calendar` | `get_maintenance_calendar` (query: `window_days`, default 30) | `admin`, `fleet_manager` |
| GET | `/api/v1/dashboard/fleet-health` | `get_fleet_health` | `admin`, `fleet_manager` |

`driver` and `mechanic` have no access to any route in this router.

All four are `GET`-only, org-scoped, and safe to expose over MCP to `ai_agents` unmodified — per `backend/CLAUDE.md`'s note that read paths free of side effects are the ones safe to hand to an LLM-driven agent.

---

## 5. Tests

- `test_summary_matches_manual_counts` — seed known data across all domains, assert every field in `DashboardSummaryResponse` against a hand-computed value.
- `test_summary_reuses_existing_service_functions` — a regression guard: mock/spy `maintenance_service.list_overdue` and `inventory_service.list_low_stock`, assert `dashboard_service.get_summary` actually calls them rather than querying those tables directly (protects the "aggregations built on top of existing service functions" principle from silently rotting).
- `test_fuel_trends_covers_requested_month_range` — including a month with zero fuel logs (should appear with `total_cost=0`, not be skipped).
- `test_maintenance_calendar_includes_far_overdue_items` — an item overdue by 60 days still appears even though `window_days=30`.
- `test_maintenance_calendar_excludes_far_future_upcoming` — an item due in 90 days is excluded.
- `test_fleet_health_excludes_missing_signals_from_average` — a vehicle with no applicable `ComplianceRule` doesn't get penalized to 0 for that signal.
- `test_fleet_health_signal_thresholds` — one test per signal's bucket boundaries, once thresholds are finalized.
- `test_dashboard_endpoints_never_write` — a targeted test (or code-review checklist item) confirming no `INSERT`/`UPDATE`/`DELETE` is reachable from any function in `dashboard_service.py`.
- `test_org_scoping` — a second organization's data never influences any dashboard number.
- `test_driver_and_mechanic_forbidden_on_all_dashboard_routes` — `driver`/`mechanic` tokens get `403` on all four routes; `admin`/`fleet_manager` succeed.

---

## 6. Explicit non-goals

- Natural-language executive summaries ("Fleet fuel cost up 12%, driven by Vehicle #14...") — the `ai_agents` `ExecutiveInsights` agent, consuming these same endpoints via MCP.
- Cross-domain narrative synthesis connecting a fuel spike to a mechanic's note to a compliance gap — that connective reasoning is exactly what's reserved for the AI layer per the boundary principle; the backend's job stops at exposing the four signals cleanly, not narrating them.

Do not add a `/dashboard/insights` or `/dashboard/summary-text` endpoint here — any endpoint returning generated prose belongs in `ai_agents`, called from the frontend separately from these deterministic aggregation endpoints.
