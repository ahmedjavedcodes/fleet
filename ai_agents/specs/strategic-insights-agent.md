# Spec: Strategic Insights & Executive Dashboard Agent

*Found on disk without a corresponding plan document or a "verified against the real backend" pass, like `driver-accountability-agent.md` before it. Corrected below (`backend/app/api/dashboard.py`, `fuel.py`, `app/schemas/dashboard.py`) before implementation. Unlike the Driver Accountability draft, this one's RBAC and its two named endpoints (`/api/v1/dashboard/summary`, `/api/v1/dashboard/fuel-trends`) were exactly right — the real correction here is a duplication problem, not a fabricated capability.*

## Problem Statement

Fleet management generates fragmented data across fuel, maintenance, and incident modules; executives lack a synthesis layer and manually correlate spreadsheets. Who: `admin` and `fleet_manager` only — matches the real backend's `dashboard.py` roles exactly. If not built: delayed capital-drain detection and no automated executive reporting.

## Functional Requirements

1. Dashboard KPI summary (`get_dashboard_summary_tool`, `GET /api/v1/dashboard/summary`): real response is `total_vehicles`, `active_drivers`, `month_fuel_cost`, `overdue_maintenance_count`, `low_stock_parts_count`, `open_incidents_count` (the draft's field names were approximate; these are the real ones).
2. Fuel & cost trend analysis: **`get_fuel_trends_tool` already exists** in `mcp_server/fuel_tools.py`, hitting this exact endpoint (`GET /api/v1/dashboard/fuel-trends`) with these exact roles — built during the Fuel Agent's spec. This agent imports and reuses it rather than shipping a second tool under the same name.
3. **Fleet health synthesis fetches an already-computed score; it does not recompute one.** The draft's FR 3 asked to "compute an aggregate executive health score... by correlating active vehicle records, unresolved maintenance logs, recent safety incidents, and fuel anomaly flags" — but the backend already does exactly this at `GET /api/v1/dashboard/fleet-health` (a per-vehicle composite `health_score` from 4 signals, dynamically re-normalized). Recomputing it client-side would duplicate that logic and risk drifting from it — same class of correction as the Fuel Agent's `is_anomalous` handling. `get_fleet_health_tool` fetches the real endpoint; the agent's own synthesis work is aggregating the *N* per-vehicle scores into one executive number (fleet average, count below a risk threshold) — a genuine value-add on top of real data, not a duplicate of it.
4. Cross-domain cost correlation: `/api/v1/dashboard/fuel-trends` is fleet-wide with no per-vehicle breakdown ("no row-level filtering anywhere — every number here is fleet-wide by definition", per the backend's own comment), so per-vehicle fuel cost for a given month comes from a different, new tool instead: `get_fuel_summary_tool` (`GET /api/v1/fuel/summary`, real roles `admin`/`fleet_manager`), whose `by_vehicle` field has per-vehicle totals. Paired with `get_maintenance_logs_tool` (reused from the Maintenance Agent) summed by `vehicle_id`, `correlate_costs` merges the two into one row per vehicle, sorted descending by combined cost — a plain ranking, not a predictive model.
5. MCP tools (`ai_agents/mcp_server/insights_tools.py`): `get_dashboard_summary_tool`, `get_fleet_health_tool` (new), `get_fuel_summary_tool` (new). `get_fuel_trends_tool` (reused from `fuel_tools.py`) and `get_maintenance_logs_tool` (reused from `maintenance_tools.py`) are not redefined here.
6. RBAC: every tool this agent touches — its own three plus the two reused ones — is restricted to **admin, fleet_manager** for this agent's purposes. The two reused tools have their own, broader role sets on their home agents (`get_fuel_trends_tool` matches exactly; `get_maintenance_logs_tool` also permits `mechanic`), so this agent adds its own blanket gate right after `inject_context` rather than trusting each reused tool's gate alone — otherwise a `mechanic` could reach `cost_analysis` through the maintenance-logs call.
7. Query support for dashboard summary, fuel trends, and fleet health, per FR 6's roles.

## Behaviour

- **executive_summary:** `inject_context → checking_access → classify_intent → fetch dashboard summary + fuel trends + fleet health → synthesize the fleet-health aggregate → reply`.
- **cost_analysis:** `inject_context → checking_access → classify_intent → fetch fuel summary + maintenance logs → correlate_costs → reply`.
- **query:** `inject_context → checking_access → classify_intent → call the matching tool → return results`.
- States: Intent = `executive_summary | cost_analysis | query`, decided from an explicit `request_type` the caller sets — unlike the other four agents, there's no document/image to structurally infer intent from; this is a pure read/synthesis agent with no extraction skill at all.

## Constraints

- Reuses `ai_agents/tools/{api_client,auth_context}.py` and imports tools from `mcp_server/{fuel_tools,maintenance_tools}.py` rather than duplicating them.
- Real endpoint paths: `/api/v1/dashboard/summary`, `/api/v1/dashboard/fuel-trends`, `/api/v1/dashboard/fleet-health`, `/api/v1/fuel/summary`, `/api/v1/maintenance`.
- Read-only: no write operations anywhere in this agent.

## Edge Cases and Error Handling

| Trigger | Expected Response |
|---|---|
| `driver` or `mechanic` attempts any insights request (summary, cost analysis, or query) | Refused at the blanket access check, before any backend call. |
| Backend returns an empty fleet-health list or empty cost data | Synthesis reports zero-state counters (`average_health_score: None`, `at_risk_count: 0`) rather than crashing. |
| A backend call fails during multi-endpoint aggregation | Caught as `BackendAPIError`; the agent halts with that error as the reason, no partial/inconsistent synthesis is returned. |

## Acceptance Criteria

1. **Given** admin/fleet_manager credentials, **when** requesting an executive summary, **then** dashboard KPIs, fuel trends, and the fleet-health aggregate are fetched and returned together.
2. **Given** a cost-analysis request, **when** synthesized, **then** fuel and maintenance costs are correlated per vehicle and sorted by combined cost descending.
3. **Given** a `driver` or `mechanic` caller, **when** any of executive_summary, cost_analysis, or a query is attempted, **then** the agent refuses before any backend call.
4. **Given** backend availability, **when** querying fuel trends, **then** the real trend data returns unmodified.
5. **Given** an empty fleet (no vehicles with health scores), **when** `executive_summary` runs, **then** it completes with zero-state counters instead of a crash or division error.
6. **Given** a backend call fails mid-aggregation, **when** either `executive_summary` or `cost_analysis` runs, **then** the agent halts with a clean diagnostic reason.
7. **Given** the MCP tools and synthesis functions, **when** the test suite runs, **then** all are covered by `pytest` using an injected-dependency fake backend (same pattern as the other four agents) — no live infrastructure required.
