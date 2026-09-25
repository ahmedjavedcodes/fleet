# Spec 01 — Fuel Vision & Leakage Auditor Agent (`Fuel Agent`)

## 1. Overview & Objectives

The Fuel Agent is the second specialized multi-agent workflow in the Fleet SaaS platform. It automates fuel receipt processing, trip sheet ingestion, and real-time efficiency auditing to prevent fuel leakage, theft, and unauthorized spending.

### Core Capabilities

- **Vision Receipt Extraction:** Parses paper fuel receipts (JPEG/PNG) to extract station names, dates, volume, cost, and vehicle odometers.
- **Odometer Continuity Validation:** Validates that incoming mileage readings strictly advance over previous logs (preventing odometer rollbacks or invalid entries).
- **Efficiency & Leakage Auditing:** Computes consumption metrics (liters / distance or cost-per-km) and flags anomalies when fuel spikes exceed historical thresholds by >20%.
- **RBAC Enforcement:** Restricts create operations based on caller roles (`admin`, `fleet_manager`, `driver`), while scoping query tools securely.

---

## 2. Directory & Module Structure

Following the repository's established conventions (`ai_agents/`), the Fuel Agent will reside under a dedicated package:

```text
ai_agents/
├── agents/
│   └── fuel/
│       ├── __init__.py
│       ├── graph.py                  # LangGraph state machine for fuel/trip ingestion
│       ├── efficiency_auditor.py     # Sub-agent for anomaly and leakage detection
│       └── state.py                  # TypedDict defining AgentState for fuel workflows
├── mcp_server/
│   └── fuel_tools.py                 # Thin, RBAC-gated MCP tool wrappers for backend APIs
└── tools/
    └── file_parsers.py               # Expanded to include extract_fuel_receipt()
```

---

## 3. Data Schemas (`ai_agents/tools/schemas.py` additions)

### Vision Extraction Output (Pre-bridge, Pre-sanitize)

```python
class FuelReceiptExtraction(BaseModel):
    station_name: str | None = None
    receipt_date: date | None = None
    liters: float | None = None
    total_cost: float | None = None
    odometer: int | None = None
    plate_number: str | None = None
```

### Backend-Ready Create Inputs

```python
class FuelLogCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vehicle_id: str
    driver_id: str
    liters: float
    total_cost: float
    odometer: int
    station_name: str | None = None
    receipt_date: date | None = None

class TripLogCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vehicle_id: str
    driver_id: str
    distance_km: float
    start_odometer: int
    end_odometer: int
    trip_date: date | None = None
```

---

## 4. MCP Tool Catalog (`ai_agents/mcp_server/fuel_tools.py`)

| Tool Name | Backend Endpoint | Method | Permitted Roles | Description |
| --- | --- | --- | --- | --- |
| `get_fuel_logs_tool` | `/api/v1/fuel-logs` | `GET` | `admin`, `fleet_manager`, `driver` | Fetch fuel log history (scoped by org/role). |
| `create_fuel_log_tool` | `/api/v1/fuel-logs` | `POST` | `admin`, `fleet_manager`, `driver` | Submits validated fuel entries and updates vehicle odometers. |
| `get_trip_logs_tool` | `/api/v1/trip-logs` | `GET` | `admin`, `fleet_manager`, `driver` | Fetch route distance and trip histories. |
| `create_trip_log_tool` | `/api/v1/trip-logs` | `POST` | `admin`, `fleet_manager`, `driver` | Records a completed route trip log. |
| `get_fuel_trends_tool` | `/api/v1/dashboard/fuel-trends` | `GET` | `admin`, `fleet_manager` | Retrieves aggregated cost and consumption analytics. |

---

## 5. LangGraph State Machine Flow (`ai_agents/agents/fuel/graph.py`)

```text
inject_context 
    → classify_intent (receipt_onboard vs. trip_log vs. query_trends)
    → [receipt_onboard] extract_receipt 
    → sanitize_fuel_data 
    → validate_odometer_continuity 
    → audit_fuel_efficiency (leakage check)
    → create_fuel_log (via MCP tool)
    → END
```

### Key Sub-Agent Guardrails

1. **Odometer Continuity Sub-Agent:** Compares the receipt's odometer reading against the vehicle's last recorded odometer via `get_vehicles_tool`. If `receipt.odometer <= last_odometer`, execution halts with a continuity error.
2. **Leakage Auditor Sub-Agent:** Computes consumption efficiency. If cost-per-kilometer exceeds rolling historical baselines by +20%, a warning flag is attached to the session and logged for the Fleet Manager.

---

## 6. Acceptance Criteria (Test Specification)

- **AC 1 (Receipt Vision Parsing):** A photographed fuel receipt correctly extracts liters, cost, and odometer data using the LLM provider fallback.
- **AC 2 (Odometer Rejection):** Sub-agent successfully blocks backdated or lower odometer readings, returning a clean halt reason.
- **AC 3 (Efficiency Spikes):** Leakage auditor flags abnormal fuel consumption deviations without crashing the ingestion pipeline.
- **AC 4 (RBAC Gating):** Drivers can log their own fuel, while analytics/trends queries correctly enforce manager/admin clearance.
- **AC 5 (Dependency Injection):** Graph executes fully in unit tests using in-memory fakes without live network or database dependencies.
