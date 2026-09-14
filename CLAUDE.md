# CLAUDE.md

**Project:** Autonomous Fleet Management SaaS (Phase 3)
**Domain:** Commercial Fleet & Transport (No Real-Time Hardware/IoT)

## Project Vision & Context

You are working on an enterprise-grade full-stack platform designed to solve operational, maintenance, and compliance bottlenecks for commercial fleets.

**CRITICAL CONSTRAINT:** This system operates **entirely without real-time hardware, IoT trackers, or GPS integrations**. All data relies on historical company records, manual log entries (mechanic logs, driver reports), and uploaded documents (receipts, CSVs, PDFs).

The goal is to move from reactive firefighting to predictive intelligence using multi-model LLM orchestration, Model Context Protocol (MCP), and autonomous agent workflows.

---

## Problem Statements & Solutions

Based on fleet managers' core challenges, the system directly targets the following pain points through data-driven analysis:

* **Fuel Price Volatility:** Constant fluctuations in petroleum prices heavily drain budgets. *Solution:* The system analyzes manual fuel logs and receipts to forecast profit margins and delivery costing.
* **Unpredictable Spare Parts:** Sourcing genuine spare parts is hindered by import restrictions. *Solution:* The platform analyzes historical inventory data and purchase orders to predict part shortages.
* **Frequent Breakdowns & Poor Maintenance:** A reliance on reactive repairs causes unexpected downtime. *Solution:* The system uses manually entered mechanic logs and mileage updates to schedule preventive maintenance.
* **Driver Accountability & Asset Misuse:** Frictions arise over vehicle delays and conditions. *Solution:* By digitizing driver reports and incident logs, the system creates an auditable trail of accountability.
* **Route & Traffic Inefficiencies:** Without real-time tracking, navigating congested infrastructure causes wasted fuel. *Solution:* The system analyzes historical trip durations and driver-reported route data to recommend optimal static routing and scheduling.
* **Compliance & Manufacturer Guidelines:** Monitoring regulatory datasets across multiple dates. *Solution:* Adhering strictly to manufacturer maintenance guidelines based on logged odometer readings.
* **Strategic Insights:** Siloed, manually entered vehicle operational data. *Solution:* Transforming raw inputs into high-level predictive executive insights.
* **Road Accidents:** Risk patterns affecting driver safety and asset uptime. *Solution:* Analyzing manually reported accident logs to identify and mitigate recurring risk factors.
* **Shift Scheduling:** Reliance on manual spreadsheets and messaging apps. *Solution:* An AI-assisted roster management system to eliminate operational bottlenecks.

---

## Technology Stack

- **Frontend:** Next.js (App Router), TypeScript, Tailwind CSS, Lucide Icons, Recharts.
- **Backend (Core API):** FastAPI (Python), SQLAlchemy, Alembic, Pydantic v2.
- **AI / Agentic Module:** LangChain, LangGraph, Model Context Protocol (MCP).
- **Database (Relational):** PostgreSQL (for relational data like users, logs, and fleet metadata).
- **Database (Vector):** Pinecone (for semantic memory, vector search, and RAG).
- **LLM Strategy:** Multi-provider (e.g., local Llama 3 + Claude via API/OpenRouter).
- **Tooling:** `uv` (Python package manager), Docker & Docker Compose, Pytest.

---

## AI Assistant Directives & Development Rules

When writing code or assisting with this project, you must adhere to the following rules:

1. **Maintain Transparency (`prompts.md`):** You must log every significant architectural decision, prompt iteration, and tool execution in the `prompts.md` file.
2. **AI-Assisted Testing:** Every new feature must be accompanied by relevant unit tests (pytest for backend/agents) and API integration tests.
3. **Safety & Read-Only Hooks:** When implementing agentic database access, ensure that a `pre_tool_call` safety hook is always used to inspect generated SQL, strictly enforcing **read-only** execution to protect manual data integrity.
4. **Data Reality Check:** Never write features that assume live telemetry. Always route data ingestion through file uploads (CSV/PDF) or manual form entry.
5. **Strict Typing:** Use Pydantic v2 for all backend data validation and strict TypeScript interfaces on the frontend.
6. **Modular Separation:** Treat the `backend` (CRUD, Auth, API) and `ai_agents` (LangGraph, MCP, memory) as completely distinct modules. They should communicate via defined APIs or MCP, not tight code coupling.

---

## Core Agent Architecture: `FleetCopilot`

The system is driven by **LangGraph Orchestration**, managed in the independent `ai_agents` module:

* **Model Context Protocol (MCP):** Use MCP client/server bindings to securely connect the LLM to PostgreSQL for querying historical fleet records, parts inventory, and shift logs.
* **Agent Memory:** Utilize conversational buffer memory for short-term context and persistent **Pinecone vector memory** for long-term recall (e.g., matching historical vehicle breakdown patterns from mechanic notes).
* **Plugins / Skills (File I/O):** Implement modular Python functions as agent tools specifically for parsing driver trip sheets (CSV) and supplier invoices (PDF).

---

## Directory Structure & Navigation

Adhere to the decoupled architectural structure when creating or modifying files:

```text
fleet-saas/
├── backend/              # Core REST API, Auth, and Database Management
│   ├── app/
│   │   ├── api/          # FastAPI routers (Auth, Vehicles, ManualLogs)
│   │   ├── core/         # Config, Database session, Security
│   │   ├── models/       # SQLAlchemy models (User, Vehicle, TripLogs, Maintenance)
│   │   ├── schemas/      # Pydantic v2 validation schemas
│   │   └── services/     # Core business logic and standard CRUD operations
│   ├── tests/            # Pytest unit & integration tests for the API
│   └── alembic/          # Database migrations
│
├── ai_agents/            # Decoupled Autonomous Agentic Framework
│   ├── agents/           # LangGraph workflows, sub-agent definitions
│   ├── mcp/              # MCP server/client configurations for DB and tools
│   ├── tools/            # Custom tools, File I/O parsing, Hooks & Safety interceptors
│   ├── memory/           # Pinecone vectorization pipelines, memory buffers
│   ├── core/             # LLM provider configurations and prompt templates
│   └── tests/            # Agent evaluations and execution tests
│
├── frontend/             # Next.js Dashboard
│   ├── src/
│   │   ├── app/          # App Router pages (Dashboard, Log Entry, Agent Chat)
│   │   ├── components/   # UI components, dropzones, Recharts, chat drawer
│   │   └── lib/          # API clients, MCP UI bindings, and state management
│
├── prompts.md            # Ongoing AI interaction and prompt log
└── docker-compose.yml    # Local multi-container orchestration (Backend + Agents + Frontend)
```
