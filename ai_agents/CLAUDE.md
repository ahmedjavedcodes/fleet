# CLAUDE.md — AI Agents Module (`ai_agents/`)

**Scope:** This file governs the `ai_agents/` module only. It extends, and does not
replace, the root [`CLAUDE.md`](../CLAUDE.md) — directives #1–#6 there (transparency
log, testing, read-only safety hooks, no live telemetry, strict typing, modular
separation) apply to everything in this module.

---

## 1. Module Overview & Project Context

**One-line goal:** Build an agentic intelligence layer on top of our verified FastAPI
backend (Specs 00–05 + Vehicle Assignment) using the Model Context Protocol (MCP) and
Vision/Text LLMs.

**Core architecture (request flow):**

```
Specialized AI Agents  →  MCP Tool Server  →  FastAPI Backend REST API  →  PostgreSQL
   (LangGraph nodes)        (ai_agents/mcp)      (backend/app/api)        (Engine)
```

Agents never touch the database directly for **writes**. Mutating actions (creating a
fuel log, filing an incident, drafting a PO) go through the backend's REST API, which
already enforces auth, RBAC, org-scoping, and business validation. The only direct
database path an agent may use is the read-only MCP SQL tool, gated by the
`pre_tool_call` safety hook (see [§5](#5-mcp-server--tool-catalog)).

**Status of foundation:** The backend is 100% complete, verified live, and covered by
270/270 passing unit/integration tests. Treat `backend/app/api`, `backend/app/models`,
and `backend/app/schemas` as a stable contract — if an agent needs data or an action
the backend doesn't expose yet, that's a backend change request, not a reason to query
tables directly or bypass the API.

---

## 2. Backend Baseline — What Data & Behavior Already Exists

Agents should be built assuming the following is already true, verified, and tested.
This is the "world model" an agent's tools operate on.

- **Spec 00 (Foundation & Multi-Tenancy):** JWT auth, organization scoping via
  `OrgScopedMixin` (every query is implicitly filtered to the caller's org), 4 RBAC
  roles (`admin`, `fleet_manager`, `driver`, `mechanic`), Vehicle & Driver CRUD.
- **Spec 01 (Fuel & Efficiency):** Fuel logging, atomic odometer sync on each fuel
  entry, cost-per-km computation, >20% fuel efficiency anomaly detection.
- **Spec 02 (Spare Parts & POs):** Inventory stock management with pessimistic locking
  (`SELECT ... FOR UPDATE`) on decrement, Purchase Orders, automated supplier
  reliability scoring.
- **Spec 03 (Maintenance & Compliance):** 1:1 mechanic service logs, auto-decrement of
  spare parts stock on service completion, dynamic compliance schedule matrix
  (`compliant`, `due_soon`, `overdue`) driven by logged odometer readings.
- **Spec 04 (Driver Accountability):** Trip logs, append-only shift reports (a `PATCH`
  or `PUT` on an existing shift report returns `405`), immutable incident logs
  (Pydantic schemas use `extra="forbid"`), database-native `UNION ALL` chronological
  timelines per vehicle/driver.
- **Spec 05 (Strategic Insights Dashboard):** Read-only executive summary, 12-month
  fuel trend series, 30-day maintenance calendar, 4-signal composite vehicle health
  score with dynamic signal re-normalization when a signal is unavailable.
- **Vehicle Assignment Module:** Real-time custody state (`released_at IS NULL` marks
  an active assignment), take/leave condition tracking, shift duration calculation,
  point-in-time custody queries ("who had vehicle X on date Y").

**Data reality reminder:** every one of these is built from manual log entries,
uploaded CSVs/PDFs, and historical records — never live GPS or telemetry. Agent
reasoning, tool descriptions, and any prompts you write must not imply real-time
tracking (e.g. don't write a tool description like "get vehicle's current location").

---

## 3. Directory Responsibilities

```
ai_agents/
├── agents/     # LangGraph graphs & nodes (e.g. fleet_copilot.py) — orchestration only,
│               # no direct DB or HTTP calls; call tools/ instead
├── core/       # LLM provider config (core/llm_config.py), prompt templates
├── mcp/        # MCP server exposing read-only SQL + backend-API-backed tools
├── memory/     # Agent memory client: embedders, summarizer, AgentMemory (storage is in backend/)
├── tools/      # Custom tools: file parsers, HTTP client to backend, safety hooks
├── tests/      # pytest agent evaluations and execution tests
└── .env.example
```

Rule of thumb: if code decides *what to do next* (graph control flow, planning), it
belongs in `agents/`. If code *does a thing* (calls the backend, queries Postgres,
parses a CSV, embeds text), it belongs in `tools/`, `mcp/`, or `memory/`. Agents call
tools; tools never call agents.

---

## 4. Current Implementation Status

Be explicit with yourself and the user about what's real vs. scaffolding before
building on top of it:

| File | Status |
| :--- | :--- |
| `tools/safety_hooks.py` | **Implemented.** `pre_tool_call` rejects anything but a single `SELECT`/`WITH` statement, blocks write keywords, blocks multi-statement input. Covered by `tests/test_safety_hook.py`. |
| `mcp/server.py` | **Scaffolded.** Registers one tool (`query_fleet_data`) that runs SQL through the safety hook, but execution against a real read-only session is not wired up yet (see the `NOTE` in that file re: package-name collision with the installed `mcp` SDK — resolve before shipping). |
| `agents/fleet_copilot.py` | **Scaffolded.** A one-node LangGraph graph (`respond`) that passes state through unchanged. No LLM call, no tool binding, no routing logic yet. |
| `core/llm_config.py` | **Implemented.** `get_chat_model()` returns a configured LangChain chat model for `local_llama`, `claude_anthropic`, or `claude_openrouter`, with lazy provider imports. |
| `memory/` | **Implemented.** `AgentMemory` (`service.py`), embedders (`embeddings.py`: none/pinecone/ollama/nomic), background summarizer, staleness extraction. Talks only to the backend's `/api/v1/memory/*` — never to Pinecone storage directly. |
| `tools/file_parsers.py` | **Present, not yet reviewed here** — check the file directly before assuming a parser exists for a given format. |
| MCP tool catalog (§5 table) | **Design target, not yet implemented.** Only `query_fleet_data` exists today. Treat the table below as the spec to build against, not a description of current code. |

When you pick up work in this module, re-verify this table against the actual files —
it will go stale as soon as someone implements the next tool.

---

## 5. MCP Server & Tool Catalog

### 5.1 Two kinds of MCP tools

1. **Read-only SQL tool** (`query_fleet_data`, implemented) — for ad-hoc analytical
   questions that don't map cleanly to a single backend endpoint (e.g. cross-table
   trend questions). Every call passes through
   `tools.safety_hooks.pre_tool_call` first. This is the *only* place raw SQL is
   allowed to originate from an agent.
2. **Backend-API-backed tools** (design target, table below) — thin wrappers that call
   the FastAPI backend over HTTP with the agent's bearer token. These are how agents
   perform actions (create a log, file an incident, draft a PO) and how they fetch
   data that already has a well-defined endpoint. Prefer these over raw SQL whenever
   an endpoint exists — they inherit the backend's validation, RBAC, and org-scoping
   for free.

### 5.2 Planned tool → route mapping

| Backend Route | Method | MCP Tool Name | Tool Purpose & Behavior |
| :--- | :---: | :--- | :--- |
| `/api/v1/auth/login` | `POST` | `authenticate_agent` | Obtain a bearer token for system operations. |
| `/api/v1/vehicles` | `GET` | `get_vehicles_list` | Filter vehicles by status, plate, or make/model. |
| `/api/v1/drivers` | `GET` | `get_drivers_list` | Fetch the active driver roster. |
| `/api/v1/fuel-logs` | `POST` | `create_fuel_log` | Submit a fuel entry; triggers the backend's atomic odometer update. |
| `/api/v1/fuel-logs` | `GET` | `get_fuel_efficiency_trends` | Analyze cost/km metrics and efficiency spikes. |
| `/api/v1/parts` | `GET` | `list_low_stock_parts` | Fetch parts below minimum reorder threshold. |
| `/api/v1/purchase-orders` | `POST` | `create_purchase_order` | Auto-draft a PO for low-stock inventory. |
| `/api/v1/compliance/matrix` | `GET` | `get_compliance_matrix` | Check dynamic fleet service-rule compliance. |
| `/api/v1/incidents` | `POST` | `file_incident_report` | File a new asset damage / safety incident. |
| `/api/v1/vehicles/{id}/timeline` | `GET` | `get_vehicle_timeline` | Retrieve the chronological `UNION ALL` audit feed. |
| `/api/v1/drivers/{id}/timeline` | `GET` | `get_driver_timeline` | Retrieve the unified driver activity timeline. |
| `/api/v1/dashboard/summary` | `GET` | `get_dashboard_summary` | Read-only executive summary metrics. |
| `/api/v1/dashboard/fleet-health` | `GET` | `get_fleet_health_scores` | Fetch composite 4-signal health ratings. |
| `/api/v1/vehicles/{id}/assign` | `POST` | `assign_vehicle_custody` | Hand over vehicle custody to a driver. |
| `/api/v1/vehicles/{id}/release` | `POST` | `release_vehicle_custody` | Release custody & log handover condition. |

Before implementing a row: confirm the exact route path and response shape against the
matching router in `backend/app/api/` — this table is a mapping spec, the router
source is the contract.

### 5.3 Tool naming & shape conventions

- Tool names are `snake_case` verbs describing the effect (`create_*`, `get_*`,
  `list_*`, `assign_*`, `release_*`, `file_*`) — mirror the table above rather than the
  HTTP method.
- Every write tool (`create_*`, `assign_*`, `release_*`, `file_*`) must accept a
  Pydantic v2 input model and return the backend's response body unmodified (no
  agent-side reshaping that could hide a validation failure).
- Every read tool must support the same filter/pagination parameters the backend route
  exposes — don't silently narrow (e.g. hardcode a date range) what the underlying
  endpoint allows.

---

## 6. Safety & Read-Only Enforcement

Per root directive #3, **any** agentic path that can reach the database directly (not
through the backend API) must go through `tools/safety_hooks.pre_tool_call` before
execution. Concretely:

- `mcp/server.py`'s `call_tool` handler already does this for `query_fleet_data` — keep
  that call site intact when wiring up real execution.
- If you add a second SQL-capable tool, it must call `pre_tool_call` too. Don't assume
  the hook is global middleware — it isn't; each call site is responsible for invoking
  it.
- The hook currently rejects: empty input, anything not starting with `SELECT`/`WITH`,
  multi-statement input (`;` anywhere in the body), and any of `INSERT, UPDATE,
  DELETE, DROP, ALTER, TRUNCATE, CREATE, GRANT, REVOKE, MERGE, REPLACE` as a whole
  word (case-insensitive). Extend `_WRITE_KEYWORDS` in `tools/safety_hooks.py` if a new
  write-capable SQL construct needs blocking — don't special-case it downstream.
- Defense in depth: even with the hook in place, the DB credential used by the MCP
  server's session should itself be a Postgres role with `SELECT`-only grants. The
  hook protects against a misbehaving LLM; the role protects against a bug in the hook.
- Backend-API-backed tools (§5.2) don't need `pre_tool_call` — the backend's own
  Pydantic validation, RBAC, and org-scoping are the enforcement layer there. The hook
  is specifically for the raw-SQL escape hatch.

---

## 7. Agent Memory

Grand Orchestrator memory follows `specs/agent-memory.md` and
`specs/Pinecone_Migration_Hardened.md`. **Storage is owned by the backend**:
Postgres is the system of record (`backend/app/models/memory.py`), Pinecone holds
the vectors (`backend/app/services/vector_store.py`), and `ai_agents/` reaches both
only via `/api/v1/memory/*` — it never touches Postgres or the Pinecone index.

- **Short-term:** `agent_sessions` / `agent_messages` with a running summary kept
  bounded by `memory/summarizer.py` (background, never on the hot path).
- **Long-term:** `semantic_memories`, scoped `personal | organization | entity`; the
  backend enforces who may read/write each scope, pins every Pinecone call to the
  caller's org, and re-checks every vector hit against Postgres. LLM-proposed facts
  are saved only through the HITL-gated `update_memory` tool.
- **Embeddings:** `memory/embeddings.py`, 768-dim, via
  `MEMORY_EMBEDDER=none|pinecone|ollama|nomic`. With `none`, recall falls back to
  scope + keyword matching — never generate placeholder vectors.
- **Entry point:** `memory/service.py`'s `AgentMemory`, injected as
  `OrchestratorDeps.memory` (default `None` = memory off).

---

## 8. File I/O Tools (Plugins/Skills)

`tools/file_parsers.py` is the home for parsing driver trip sheets (CSV) and supplier
invoices (PDF) into structured data an agent can act on. Per root directive #4, these
parsers are the *only* ingestion path for this kind of data — never add a code path
that assumes a live feed. When adding a new parser:

- Return Pydantic v2 models, not raw dicts, so downstream tool calls get the same
  validation guarantees as the backend API.
- Fail loudly on malformed input (don't silently skip rows) — this data ultimately
  feeds compliance and accountability records, so silent data loss is worse than a
  visible parse error.

---

## 9. Testing Expectations

Per root directive #2, every new tool, hook, or graph node needs test coverage in
`ai_agents/tests/`:

- **Safety hook changes:** extend `tests/test_safety_hook.py` — every new blocked
  pattern needs a case proving it's rejected, and every legitimate `SELECT`/`WITH`
  shape you rely on elsewhere needs a case proving it's *allowed*.
- **New MCP tools:** test the tool function directly with a mocked backend HTTP client
  (write tools) or a mocked DB session (the SQL tool) — don't require a live backend
  or live Postgres for unit tests.
- **New graph nodes:** test state transitions in isolation (input state → output
  state) before testing the compiled graph end-to-end.
- Run tests with `uv run pytest` from `ai_agents/` (see `pyproject.toml` —
  `testpaths = ["tests"]`, `pythonpath = ["."]`).

---

## 10. Cross-Module Boundary

Per root directive #6: `ai_agents/` and `backend/` communicate only through the
backend's REST API (or, for reads, through the read-only MCP SQL path). Concretely:

- Never `import` from `backend.app.*` inside `ai_agents/`. If a Pydantic schema needs
  to be shared, duplicate the minimal shape in `ai_agents/` rather than reaching across
  the module boundary — they're allowed to drift slightly since one validates HTTP
  input and the other validates tool input.
- The `mcp/server.py` docstring already flags a real packaging issue: the local
  `ai_agents/mcp` package shadows the installed `mcp` SDK package when `ai_agents/` is
  on `sys.path` (as it is for tests). Resolve this (e.g. src-layout, or renaming the
  local package) before connecting a real LLM client to this server — don't build more
  on top of the collision.

---

## 11. Transparency Log Reminder

Per root directive #1: log architectural decisions, prompt iterations, and tool
executions of note in [`prompts.md`](../prompts.md) at the repo root — not in this
file. This file documents *how the module is structured*; `prompts.md` documents *how
we got here*.
