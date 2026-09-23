# Spec: FleetLiveObserver (Execution Hooks & Telemetry)

*Found on disk without a plan document or a verification pass, same profile as several specs before it. This one asked for something that conflicts with a hard architectural rule already established for this codebase — resolved below, not silently built around.*

## Problem Statement

Unchanged: the orchestrator is a black box during execution — no cost/latency audit trail, no real-time UI feedback without paying for a second LLM call to generate it. Confirmed real and solvable without LLM cost, by building it.

## Functional Requirements — implemented, with two architectural resolutions

1. **Dual-channel output**: `FleetLiveObserver` (`orchestrator/callbacks.py`) maintains `ui_messages` (a list, always populated) and `traces` (redacted `LLMTrace`/`ToolTrace` records), each with an optional injectable sink (`ui_sink: Callable[[str], None]`, `sink: Callable[[Trace], Awaitable[None]]`) for a real SSE/DB bridge later.
2. **Zero-cost UI interpolation**: `orchestrator/ui_interpolation.py` implements the exact mapping table from §4, pure string formatting, no LLM call — verified by `test_ui_interpolation.py` and, end-to-end, by `test_orchestrator_telemetry_integration.py` asserting the UI messages a real (scripted) run produces.
3. **Token & latency extraction**: `graph.py`'s `plan`/`synthesize` nodes time the LLM call themselves (`time.monotonic()` around `deps.llm.invoke(...)`) and extract token counts via `_llm_usage()`, which checks both `AIMessage.usage_metadata` (LangChain's newer standardized field) and `response_metadata['token_usage']` (the older OpenAI-compatible shape Groq's endpoint actually returns) — neither is guaranteed present, so it degrades to `0` rather than raising.
4. **Context stamping**: `organization_id`/`user_id`/`role` are constructor arguments (the caller supplies them from the same `auth_context` the session already resolved); `trace_id` is regenerated once per session turn via `start_turn()`, called by `OrchestratorSession.run()` — **not** by `approve()`/`reject()`/`modify()`, since an approval round-trip is part of the turn that paused, not a new one (verified by `test_observer_records_hitl_pause_and_resume_under_the_same_trace_id`).
5. **Redaction**: `orchestrator/redact.py`'s `redact_payload`, recursive over dicts/lists, blocklist-by-key, case-insensitive. Extended the spec's example blocklist (`license_number`, `phone_number`, `document_text`, `image_bytes`) to also include `token`/`access_token`/`jwt` — the caller's own bearer token flows through orchestrator state (`auth_context`) the same way and is at least as sensitive.
6. **Failure isolation**: every recording method in `FleetLiveObserver` is wrapped in `try/except Exception`, logging via `logging.getLogger("fleet.telemetry")` and returning quietly — verified by three separate tests (interpolation exception, malformed trace data, sink failure never propagating).
7. **Async non-blocking writes**: `asyncio.Queue` + `run_worker()` batching consumer, exactly as specced — but **not wired into the current synchronous graph by default**. See Constraints below for why, and how it's still fully real and tested.
8. **Retry transparency**: `execute_tool` records a `schema_error` trace on every failed validation attempt (sharing one `trace_id`, incrementing `attempt`) and a `done`/`halted` trace on the eventual outcome — verified by `test_ac3_schema_error_trace_then_corrected_done_trace_share_trace_id`.

## Architectural resolutions (two real conflicts with this spec as written)

1. **§5 "Data Lifecycle & Retention" (PostgreSQL hot storage, S3/Parquet cold storage) is not implemented, and isn't a gap in this branch — it's out of scope for `ai_agents/` entirely.** Root `CLAUDE.md` and `ai_agents/CLAUDE.md` both state the same rule already governing every other agent in this codebase: `ai_agents/` never writes to the database directly, only through the backend's REST API, and no such API exists for telemetry today. Building a Postgres table + S3 archival pipeline is a `backend/` feature, not something this hook can or should do unilaterally. **The default `sink` logs locally via `logging`** — which is exactly FR 6's own fallback behavior anyway — and is a one-line swap for a real sink (`httpx.post` to a future backend telemetry endpoint) once one exists. Nothing here assumes local logging is the permanent destination.
2. **`on_tool_start`/`on_tool_end` don't fire automatically just by attaching this handler to a graph run.** The spec assumes LangChain's own tool-execution runtime is in play, but the orchestrator's `execute_tool` node (`graph.py`) dispatches sub-agents itself — it reads `tool_calls` directly off the LLM's response and calls `SubAgentRunner` in plain Python, never invoking a real LangChain `Tool.run()`/`.ainvoke()`. So `FleetLiveObserver` provides **two** APIs: the real `AsyncCallbackHandler` interface (`on_chat_model_start`, `on_llm_end`, `on_tool_start`, `on_tool_end`, etc. — correct per LangChain's actual signatures, verified against the installed `langchain-core`), which would fire correctly in a future `graph.astream_events(..., config={"callbacks":[observer]})` execution path; and a plain **sync recording API** (`record_node`, `start_tool_call`, `record_tool_result`, `record_llm`) that `graph.py` calls explicitly at the right points today. Both build the same redacted trace schemas through shared logic — this is not two parallel implementations, just two entry points into one.

## Data Schemas — implemented exactly as specced

`orchestrator/audit_schemas.py`'s `LLMTrace`/`ToolTrace` match §3 field-for-field (both `extra="forbid"`, `timestamp` defaulted via `datetime.now(timezone.utc)`).

## UI Interpolation Mapping — implemented exactly as specced

`orchestrator/ui_interpolation.py` matches §4's table row-for-row, including the "falls back to a safe generic string" rule for a missing arg or an unmapped tool/node name.

## Integration Points — one correction

- **`orchestrator/callbacks.py`**: as specced.
- **`orchestrator/session.py`**: updated to call `observer.start_turn()` and thread `record_tool_result` calls through `_resume()` — **not** updated to use `astream_events`/`astream` or bridge to a FastAPI `StreamingResponse`, since no FastAPI route exists anywhere in this codebase yet (the same standing gap flagged on every prior agent spec: nothing wraps any orchestrator or sub-agent graph in an HTTP endpoint). `observer.ui_messages`/`ui_sink` are shaped to be trivially pluggable into a `StreamingResponse(observer.ui_messages, media_type="text/event-stream")`-style route whenever that endpoint is built — this branch makes that the very next step, not a redesign.

## Edge Cases and Error Handling — verified

| Trigger | Verified Behaviour |
|---|---|
| Input payload contains `license_number`/`image_bytes` | Redacted before `ToolTrace` instantiation — `test_ac1_*`. |
| DB/sink timeout or an interpolation exception | Swallowed, logged locally, ReAct loop unaffected — `test_ac2_*` (three separate failure modes tested independently). |
| LLM schema hallucination caught by the retry wrapper | `attempt=1` `schema_error` trace, then a corrected trace on success, same `trace_id` — `test_ac3_*`. |
| Standard tool routing | Interpolated UI string pushed with zero secondary LLM calls — `test_ac4_*`. |

## Acceptance Criteria — all verified

1–4: as specced, each covered by a directly-named test (see table above) plus `test_orchestrator_telemetry_integration.py`'s two end-to-end tests proving the observer is actually reached during a real orchestrator run (not just testable in isolation).

## Test coverage

36 new tests (279 total in `ai_agents/`): `test_redact.py`, `test_ui_interpolation.py`, `test_audit_schemas.py`, `test_callbacks.py` (the four ACs plus failure-isolation edge cases), `test_orchestrator_telemetry_integration.py` (observer wired through a real — scripted — orchestrator run, including a HITL pause/resume sharing one `trace_id`). All existing 243 tests still pass unchanged — `observer` is `None` by default on `OrchestratorDeps`, so every prior test's behavior is untouched.
