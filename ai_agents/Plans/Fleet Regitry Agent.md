# Plan.md — 00-Foundation Agent (Fleet Registry)

## 1. Executive Summary

The **Fleet Registry Agent** acts as the digital gatekeeper for the Autonomous Fleet SaaS (Spec 00). It is responsible for parsing, validating, and onboarding organizational entities (Vehicles, Drivers, and Suppliers). By leveraging Vision LLM skills and multi-hop validation workflows, it eliminates manual data entry errors and prevents duplicates from polluting the PostgreSQL database.

**Primary Users:** Administrators and Fleet Managers.

---

## 2. Agent Architecture

```
User Request (Text / Image / Document)
          │
          ▼
┌──────────────────────────────────────────────┐
│  Agent Router & Context Injector (LangGraph) │
│  • Injects RBAC Role & Organization ID       │
│  • Determines Intent (Onboard vs Query)      │
└─────────┬──────────────────────────┬─────────┘
          │                          │
   [ Write Workflow ]         [ Read Workflow ]
          ▼                          ▼
┌─────────────────────┐    ┌─────────────────────┐
│ Sub-Agent / Skills  │    │ MCP Tool Server     │
│ • Vision Extraction │    │ • get_vehicles_tool │
│ • Entity Validation │    │ • get_drivers_tool  │
└─────────┬───────────┘    │ • get_suppliers_tool│
          │                └─────────────────────┘
          ▼
┌─────────────────────┐
│ MCP Tool Server     │
│ • create_vehicle    │
│ • create_driver     │
│ • create_supplier   │
└─────────────────────┘
```

---

## 3. Core Component Definitions

### 3.1. Vision Extraction Skills (`ai_agents/tools/file_parsers.py`)

Skills are deterministic pre-processing functions executed locally before calling MCP HTTP endpoints.

- **`extract_license_data(image_bytes: bytes) -> dict`**
  - **Purpose:** Parses physical driver licenses via Vision LLM.
  - **Output Schema:** `first_name`, `last_name`, `license_number`, `phone_number`, `expiration_date`.

- **`extract_vehicle_doc(image_bytes: bytes) -> dict`**
  - **Purpose:** Parses vehicle registration cards or VIN plates.
  - **Output Schema:** `plate_number`, `make`, `model`, `year`, `vin`, `initial_odometer`.

### 3.2. Sub-Agents (Validation Logic) (`ai_agents/agents/foundation/`)

Sub-agents evaluate extracted data for business logic violations before hitting the database.

- **`LicenseInspectorSubAgent`**
  - Checks if the extracted `expiration_date` is valid (must be greater than the current date: 2026-09-21).
  - Rejects expired licenses and halts the workflow.

- **`PreSearchDuplicateSubAgent`**
  - Queries `get_vehicles_tool` or `get_drivers_tool` to check if a specific `plate_number` or `license_number` already exists in the system to proactively prevent 409 database conflicts.

### 3.3. MCP Tool Catalog (`ai_agents/mcp_server/foundation_tools.py`)

Standardized HTTP wrappers targeting the FastAPI backend.

| Tool Name | Backend Endpoint | HTTP Method | Permitted Roles |
| --- | --- | --- | --- |
| `get_vehicles_tool` | `/api/v1/vehicles` | `GET` | All |
| `create_vehicle_tool` | `/api/v1/vehicles` | `POST` | `admin`, `fleet_manager` |
| `get_drivers_tool` | `/api/v1/drivers` | `GET` | All |
| `create_driver_tool` | `/api/v1/drivers` | `POST` | `admin`, `fleet_manager` |
| `get_suppliers_tool` | `/api/v1/suppliers` | `GET` | All |
| `create_supplier_tool` | `/api/v1/suppliers` | `POST` | `admin`, `fleet_manager` |

---

## 4. Phased Implementation Plan

### Phase 1: Base HTTP Client & Tool Definitions

**Goal:** Establish connectivity between the AI module and the live backend.

1. Implement `call_backend()` utility in `ai_agents/tools/api_client.py` (handling JWT headers and HTTP error extraction).
2. Implement the 6 core MCP tools (GET and POST wrappers for Vehicles, Drivers, Suppliers) in `foundation_tools.py`.
3. Write `pytest` checks mocking backend responses to ensure Pydantic schema validation holds.

### Phase 2: Security Hooks & Context Injection

**Goal:** Guarantee that LLM operations cannot bypass multi-tenant and role-based access rules.

1. Implement JWT extraction middleware to pull `organization_id` and `role`.
2. Implement dynamic RBAC tool filtering (hide `create_*` tools from `driver` and `mechanic` roles).
3. Inject security context directly into the agent's system prompt.

### Phase 3: Vision Skills & Local Validation

**Goal:** Enable image ingestion and data sanitization.

1. Build `extract_license_data` and `extract_vehicle_doc` using LangChain's Vision integration.
2. Force structured Pydantic outputs from the Vision LLM (using Instructor or LangChain schema binding).
3. Implement basic Python sanitization (e.g., stripping spaces from license plates: `ABC 123` → `ABC-123`).

### Phase 4: Agent Orchestration (LangGraph)

**Goal:** Assemble skills, sub-agents, and tools into a cohesive workflow.

1. Define the LangGraph state schema for `FoundationAgentState`.
2. Build the primary router node to classify user intent (Onboarding vs Querying).
3. Wire the multi-hop workflow: Image Upload → Vision Extraction → Duplicate Check → Database Execution.

---

## 5. Definition of Done

- [ ] The agent can successfully ingest a photo of a driver's license and create a new driver in PostgreSQL.
- [ ] The agent successfully prevents the creation of a duplicate driver or vehicle plate without crashing.
- [ ] The agent explicitly refuses to execute `create_vehicle_tool` if the provided JWT token belongs to a `driver` or `mechanic`.
- [ ] 100% test coverage for MCP tools and vision parsing logic using mocked responses.
