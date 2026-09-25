# Spec: Driver Accountability & Asset Misuse Agent

*This spec was found on disk without a corresponding plan document and without the "verified against the real backend" pass the other three agents' specs went through — it read like an unvetted plan wearing a spec's filename (hedged language like "`GET /api/v1/drivers/safety` (or equivalent analytics endpoints)"). Corrected below against the real backend (`backend/app/api/incidents.py`, `drivers.py`, `app/schemas/accountability.py`, root `CLAUDE.md`'s no-GPS/no-IoT constraint) before implementation. The original's FR 3 ("Misuse & Geofence Auditing") was not just imprecise but architecturally impossible; see FR 3 below.*

## Problem Statement

Fleet management needs oversight of driver safety, incident history, and asset misuse. Unvetted incidents and unmonitored off-hours vehicle usage lead to capital losses, insurance spikes, and legal liability. Who: `admin` and `fleet_manager` (review, incident management), `driver` (files incidents and reads their own — the real backend's `/api/v1/incidents` grants driver *read* access too, row-filtered to their own records, not just write access as the original draft assumed). `mechanic` has no access to incidents or driver data in the real backend. If not built: delayed accident triage and no systematic surfacing of a driver's incident history.

## Functional Requirements

1. Extract structured data from a photographed police report/accident document or typed driver statement (`extract_incident_report`): `incident_date`, `location`, `severity` (`minor`/`moderate`/`severe`/`critical`), `incident_type` (`damage`/`violation`/`near_miss` — **required by `IncidentLogCreate` but missing from the original draft's extraction targets entirely**; defaults to `damage` when unmappable, matching the draft's own implicit focus on `damage_description`), `vehicle_plate`, `driver_name`, `damage_description`.
2. Resolve `vehicle_plate` → `vehicle_id` via `get_vehicles_tool` (required — halts if unresolved). Resolve `driver_name` → `driver_id` via `get_drivers_tool` on a best-effort basis: `IncidentLogCreate.driver_id` is nullable, so an unmatched name does not block filing the incident.
3. **Trip auditing is a plain off-hours time-window heuristic, not geofencing.** The original draft's "Misuse & Geofence Auditing Sub-Agent" (cross-referencing "authorized schedules or operating bounds") is impossible as written: root `CLAUDE.md` states this system has no real-time hardware, IoT, or GPS integration anywhere, and there is no stored "authorized schedule" or "operating bounds" data model in the backend at all. The only usable signal is each `TripLog`'s existing `start_time`/`end_time`. `audit_trips_for_off_hours` flags trips starting or ending outside a configurable hour window (default 06:00–22:00) as a proxy for human review — not a verdict, and not real misuse detection.
4. Driver safety profile: **there is no `/api/v1/drivers/safety` endpoint** (the original draft correctly hedged this). Instead, aggregate incident counts by severity from the real `GET /api/v1/drivers/{id}/timeline` endpoint (already returns a unified trips/reports/incidents feed) — computed agent-side over real data, not fetched from a fictional analytics route.
5. Bridge extraction into `IncidentCreateInput`, matching `IncidentLogCreate`'s real fields exactly (`driver_id`, `vehicle_id`, `incident_type`, `date`, `severity`, `description`, `location_description`, `estimated_cost`) — note the real field is `description`, not `damage_description`.
6. MCP tools (`ai_agents/mcp_server/accountability_tools.py`): `get_incidents_tool` (`GET /api/v1/incidents`), `create_incident_tool` (`POST /api/v1/incidents`), `get_driver_timeline_tool` (`GET /api/v1/drivers/{driver_id}/timeline`, backing the safety-profile aggregation in FR 4). Reuses `get_vehicles_tool`/`get_drivers_tool` (`mcp_server/foundation_tools.py`) and `get_trip_logs_tool` (`mcp_server/fuel_tools.py`) rather than redefining them.
7. RBAC, corrected against the real router: `get_incidents_tool` / `create_incident_tool` / `get_driver_timeline_tool` all permit **admin, fleet_manager, driver** (not "strictly admin/fleet_manager" as the original draft claimed) — `mechanic` is the one role excluded from all three. A `driver`-role caller reading `get_incidents_tool` gets back only their own incidents (server-side row filtering); requesting another driver's `get_driver_timeline_tool` gets a `403` from the backend itself.
8. When the caller's role is `driver`, force `IncidentCreateInput.driver_id` to their own `Driver.id` before calling `create_incident_tool`, regardless of what `driver_name` resolved to — `POST /api/v1/incidents` has no server-side override for this (unlike `POST /api/v1/fuel`), so an unguarded driver could file an incident attributed to someone else. **Note:** resolving "the caller's own `Driver.id`" requires a lookup — `Driver.id` is a separate primary key from `Driver.user_id` (which FKs to `User.id`, the JWT's `sub` claim) — a caller's own driver row must be found by matching `user_id`, not assumed equal to it.
9. Query support for incidents and driver safety profiles, per FR 7's read roles.

## Behaviour

- **incident_onboard:** `inject_context → classify_intent → extract_incident_report → resolve vehicle_id and driver_id (forcing own id if caller is a driver) → create_incident_tool → reply with the created incident and its severity`.
- **trip_audit:** `inject_context → classify_intent → fetch trip logs (optionally filtered to a driver/vehicle) → flag off-hours trips → return the flagged list`.
- **query:** `inject_context → classify_intent → call the matching get_*_tool (incidents, or driver_safety via the timeline aggregation) → return results`.
- States: Intent = `incident_onboard | trip_audit | query`. `incident_onboard` sub-flow = `Extracting → ResolvingEntities → Creating → Done | Halted(reason)`.

## Constraints

- Reuses `ai_agents/tools/{api_client,auth_context,sanitize}.py` and `core/llm_config.py`'s `GROQ` provider unchanged.
- Real endpoint paths: `/api/v1/incidents`, `/api/v1/drivers/{driver_id}/timeline`. No geofence, shift-schedule, or driver-safety-score endpoint exists.
- Images/documents: JPEG/PNG for photographed reports; raw text also accepted for typed driver statements (no vision call needed for plain text).
- The off-hours trip-audit heuristic is a review signal, not a policy enforcement mechanism — it cannot distinguish an authorized early/late trip from actual misuse, and has no notion of location at all.

## Edge Cases and Error Handling

| Trigger | Expected Response |
|---|---|
| Extracted `vehicle_plate` matches no vehicle | Halt before creating anything; ask for the correct plate. |
| Unreadable incident document or blurry police report photo | Halt; ask for a clearer submission. |
| `mechanic` attempts any incident/driver-timeline tool | Agent refuses before any backend call. |
| `driver` submits an incident naming another driver | Agent overrides `driver_id` to the caller's own `Driver.id` before calling `create_incident_tool`. |
| `driver` requests another driver's safety profile/timeline | Backend returns `403`; the agent surfaces it, does not retry. |
| Extraction produces no description or no valid severity | Halt — both are required, non-defaultable fields on `IncidentLogCreate`. |

## Acceptance Criteria

1. **Given** a clear accident/police report, **when** `incident_onboard` runs, **then** the vehicle resolves, the driver resolves where named, and `create_incident_tool` succeeds with the correct severity.
2. **Given** an unreadable or blurry incident report, **when** extraction runs, **then** execution halts and asks for a clearer submission.
3. **Given** an unmapped vehicle plate, **when** asset resolution runs, **then** the workflow halts and asks for verification.
4. **Given** a `mechanic` caller, **when** any incident or driver-timeline tool is attempted, **then** the agent refuses before any backend call. **Given** a `driver` caller reading their own incidents, **then** it succeeds (row-filtered); **given** the same caller requesting another driver's timeline, **then** the backend's `403` is surfaced.
5. **Given** admin/fleet_manager credentials, **when** querying incidents or a driver's safety profile, **then** correct records return.
6. **Given** a `driver` caller filing an incident naming a different driver, **when** `create_incident_tool` is called, **then** `driver_id` is overridden to the caller's own `Driver.id` first.
7. **Given** trip logs with timestamps outside the configured hour window, **when** `trip_audit` runs, **then** exactly those trips are flagged, each with a stated reason.
8. **Given** the MCP tools and `extract_incident_report`, **when** the test suite runs, **then** all are covered by `pytest` using mocked backend/vision responses via injected dependencies (same pattern as the other three agents) — no live backend or LLM call required.
