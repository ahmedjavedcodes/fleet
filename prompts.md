# Prompt & Decision Log

Ongoing log of significant architectural decisions, prompt iterations, and tool executions, per `CLAUDE.md` directive #1.

## 2026-09-14 — Initial repository scaffold

- Created decoupled directory structure: `backend/`, `ai_agents/`, `frontend/`, per the architecture defined in `CLAUDE.md`.
- Added placeholder module directories: `backend/app/{api,core,models,schemas,services}`, `backend/tests`, `backend/alembic`; `ai_agents/{agents,mcp,tools,memory,core,tests}`; `frontend/src/{app,components,lib}`.
- Added `README.md`, `.gitignore`, `docker-compose.yml` stub.
- No code implemented yet — scaffold only.

## 2026-09-21 — Fleet Registry Agent: spec, then implementation

- Wrote `ai_agents/CLAUDE.md`, the module-level directive file for `ai_agents/`, covering the MCP tool catalog, safety-hook enforcement, memory, and the cross-module HTTP-only boundary with `backend/`.
- Ran the `spec` skill against `ai_agents/Plans/Fleet Regitry Agent.md` (the Spec 00 onboarding-agent plan) to produce `ai_agents/specs/fleet-registry-agent.md`. The interview surfaced three scope decisions the plan left implicit, confirmed with the user: (1) supplier onboarding gets its own vision-extraction skill (`extract_supplier_doc`), not just vehicles/drivers; (2) update/edit of existing records stays out of scope for this agent (create + read only); (3) a vehicle document missing `fuel_type` (a required backend field no registration card states) is resolved by asking the user in-chat, not defaulting or hard-rejecting.
- Implemented the spec on branch `fleet-registry-agent`:
  - `tools/api_client.py` — `call_backend()`, the only path from `ai_agents/` to the FastAPI backend.
  - `tools/auth_context.py` — reads (never verifies) the caller's JWT for agent-layer RBAC gating and org-scoping; the backend's own signature check and live DB role re-check remain the actual security boundary.
  - `tools/schemas.py` — Pydantic v2 models duplicating the backend's create schemas' minimal shape (per the cross-module boundary rule) plus the three vision-extraction output schemas.
  - `tools/sanitize.py` — plate/VIN/phone/name/license-number normalizers, applied before any bridged payload reaches a create tool.
  - `tools/file_parsers.py` — added `extract_license_data`, `extract_vehicle_doc`, `extract_supplier_doc`, all Groq vision calls forced through `.with_structured_output()`.
  - `core/llm_config.py` — added `GROQ` and `LLAMA_API` providers (both OpenAI-compatible endpoints, same lazy-import pattern as the existing three providers).
  - `mcp_server/foundation_tools.py` (not `ai_agents/mcp/`, deliberately — that package name collides with the installed `mcp` SDK on `sys.path`, per the existing `NOTE` in `ai_agents/mcp/server.py`) — the six get/create tool wrappers, each write tool RBAC-gated via `auth_context.can_write` before any backend call.
  - `agents/foundation/` — `state.py` (`FoundationAgentState`), `license_inspector.py`, `duplicate_checker.py`, `router.py` (structural Onboard/Query classification by image presence, not an LLM call — the signal is already unambiguous), and `graph.py` wiring it all into a LangGraph state machine with every external dependency injected via `FoundationAgentDeps` for testability.
- Test suite: 69 tests (`uv run pytest` equivalent — `python -m pytest` against a scratch venv with the new deps installed), including one end-to-end graph test per Acceptance Criterion in the spec, using an in-memory fake `call_backend` rather than a live backend/Postgres. Caught and fixed two real bugs this way: PyJWT's `verify_signature: False` silently disables `verify_exp` too unless re-enabled explicitly; and the vision-extraction mime-type check was running *after* the (mocked) LLM client was constructed instead of before, which would have cost a real Groq call on every rejected upload.

## 2026-09-24 — Frontend reset to setup files only

- At the user's request, removed all frontend application code on the `frontend` branch: every page (login, dashboard, copilot, fuel, maintenance, incidents, registry), components, the auth/API client layer, middleware, types/schemas and the 8 vitest test files (`src/` and `tests/`, 45 files).
- Kept only the project setup: `package.json`/`package-lock.json`, `tsconfig.json`, `next.config.ts`, `next-env.d.ts`, `eslint.config.mjs`, `postcss.config.mjs`, `vitest.config.mts`/`vitest.setup.mts`, `Dockerfile`, `.env.example` and `frontend/CLAUDE.md`, plus empty `src/app`, `src/components`, `src/lib` (`.gitkeep`) so the directory contract stays visible.
- The removed code remains recoverable from git history (and on the `backend`/`ai-agents` branches, which were deliberately left untouched). Until a new `src/app/layout.tsx` + `page.tsx` exist, `next dev`/`next build` have no routes to serve and `npm test` finds no test files.
