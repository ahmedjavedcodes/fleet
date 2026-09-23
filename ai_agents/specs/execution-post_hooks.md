# Spec — Execution Post-Hooks (Invalidation, Alerts, Fact-Checking)

*Verified and executed against the real backend/orchestrator code. Three
real corrections found, all in the spec's own example field names/values
and its named LLM model — none change the shape of the three hooks
themselves. See the inline notes in §2–§4 and the Corrections Log at the
bottom for exact evidence.*

## 1. Problem Statement

The Grand Orchestrator safely executes sub-agents and caches read-only queries. However, the system currently lacks post-execution side effects. This leads to three specific gaps:

- **Stale Data:** Read-only caches are never cleared when the underlying database is updated.
- **Silent Execution:** Critical operational events (e.g., severe accidents, depleted inventory) remain trapped in the backend until a user explicitly asks about them.
- **Synthesis Hallucination Risk:** The final LLM synthesis node operates without a backstop, carrying a small risk of hallucinating numbers or IDs when summarizing complex data.

This specification defines three Post-Hooks to execute immediately after tool actions or LLM generations to ensure data freshness, operational awareness, and absolute output accuracy.

---

## 2. "Fresh Data" Hook (Write-Aware Cache Invalidation)

**Execution Point:** `graph.py` (inside `execute_tool`, immediately after a mutating sub-agent returns `status="done"`).

### Functional Requirements

- **Trigger:** Fires exclusively when a sub-agent completes a write action (identified by `_is_read_only_call` returning `False`) and the operation succeeds (`status="done"`).
- **Targeted Purging:** Because cache keys are currently exact SHA-256 hashes, we cannot easily guess the keys of previous reads. The hook will introduce a namespace or tag-based flush mechanism to `ExecutionCache`.
- **Rule:** If a user logs a fuel receipt for Org A (a write), the hook flushes all cached fuel and insights queries for Org A.
- **Zero LLM Cost:** Pure Python dictionary/Redis key deletion.

### Mechanics update to `cache.py`

```python
def invalidate_namespace(self, tool_name: str, organization_id: str) -> None:
    # Deletes all cache entries tagged with this tool_name and org_id
    pass
```

---

## 3. "Real-World Alert" Hook (Webhook & Event Dispatcher)

**Execution Point:** `graph.py` (inside `execute_tool`, after a tool returns its `raw_result` dictionary).

### Functional Requirements

- **Rule-Based Triggers:** Evaluates the structured `raw_result` dictionary against deterministic Python rules based on the `agent_name`.
  - **Maintenance Rule (corrected):** `stock_remaining`/`minimum_threshold` do not exist anywhere in this backend (checked `backend/app/schemas/inventory.py`). The real fields are `qty_on_hand`/`reorder_threshold` (`PartsInventoryResponse`), and they appear in two different shapes depending on which flow ran: `updated_parts` (a list of raw inventory dicts, from the `inventory_restock` flow) and `mechanic_report.low_stock_alerts` (a list of `{part_id, low_stock_alert: bool}` flags with no raw quantities at all, from the `maintenance_onboard` flow — `backend/app/schemas/maintenance.py`'s `LowStockAlert`). The real rule checks both: `qty_on_hand <= reorder_threshold` for the first shape, `low_stock_alert is True` for the second.
  - **Accountability Rule (corrected):** `incident_severity` does not exist; the real field is `severity` (`backend/app/schemas/accountability.py`'s `IncidentLogResponse`), nested under `raw_result["created_record"]`. `"High"`/`"Critical"` do not exist either — `IncidentSeverity` (`backend/app/models/enums.py`) is `minor|moderate|severe|critical`, all lowercase. The real rule: `raw_result.get("created_record", {}).get("severity") in {"severe", "critical"}`.
- **Asynchronous Dispatch:** Dropping the alert into an `asyncio.Queue` (similar to the telemetry observer) so sending the HTTP webhook does not add network latency to the Orchestrator's ReAct loop.
- **Zero LLM Cost:** Relies entirely on Python if/else logic over the strictly typed Pydantic outputs from the sub-agents.
- **No webhook endpoint exists in this codebase** (checked `docker-compose.yml`, `pyproject.toml`) — same honest-stub treatment as `FleetLiveObserver`'s telemetry sink: the default `AlertSink` logs via `logging.getLogger("fleet.alerts")`, swappable for a real HTTP POST once an endpoint exists.

---

## 4. "Truth Checker" Hook (Output Fact-Checking Guardrail)

**Execution Point:** `graph.py` (immediately following the `synthesize` node, before returning the final state).

### Functional Requirements

- **Context Comparison:** Passes the raw scratchpad (the absolute ground truth) and the `final_response` string to a fast, secondary LLM (spec named `llama3-8b-8192` on Groq — **corrected:** not available on this account, same gap `grand-orchestrator.md` already found for the main routing LLM. `FACT_CHECKER_MODEL` defaults to `ORCHESTRATOR_MODEL`'s own default, `openai/gpt-oss-20b`, confirmed working here).
- **Strict Binary Prompt:** Asks the micro-model: *"Does the Final Response contain any proper nouns, IDs, or numbers that do NOT appear in the Scratchpad? Reply only with YES or NO."*
- **Fail-Safe Routing:**
  - If `NO` → Return response to user.
  - If `YES` → Append an internal warning to the state and force the `synthesize` node to run one more time with the instruction to correct the hallucination.
  - Bounded by `MAX_FACT_CHECK_RETRIES = 2` (not in the spec's literal text) — an unbounded checker-flags-every-draft loop is the same class of risk `grand-orchestrator.md`'s own `MAX_HOPS` addition guards against, applied here to the synthesize↔fact_check cycle.
  - **Fails open:** any exception from the checker call (bad key, network error, unparseable reply) returns "no hallucination detected," never blocking or crashing the primary response — this hook is a backstop, not a new point of failure.
- **LLM Cost:** Requires a lightweight LLM call, but is restricted to a few tokens (returning "YES" or "NO") using a highly optimized model to minimize latency.

---

## 5. Integration Blueprint

- **Wave 1 — Cache Invalidation:** Update `cache.py` to support tags (so we can group cache entries by `tool_name` + `org_id`). Then, update `graph.py` to call `deps.cache.invalidate_namespace(...)` whenever a write succeeds.
- **Wave 2 — Webhooks:** Create `orchestrator/webhooks.py` with an async queue and rule engine, injecting it into `OrchestratorDeps`.
- **Wave 3 — Fact-Checking:** Add a conditional edge in `graph.py` after `synthesize`. If the fact-check fails, the graph loops back to `synthesize`; if it passes, it proceeds to `END`.

---

## 6. Acceptance Criteria

1. Given the cache holds a dashboard summary for Org A, when a user assigns a vehicle in Org A, then the invalidation hook purges the dashboard cache so the next read reflects the new assignment. — Verified end-to-end via a real `OrchestratorSession` (`test_ac1_write_invalidates_cached_reads_for_own_and_insights_namespace`): a cached `insights` read, followed by an `assignment` write, followed by a repeated `insights` read that reaches the sub-agent runner again instead of returning the stale cached value.
2. Given the accountability agent returns `{"severity": "Critical"}`, when the sub-agent completes, then the webhook hook silently drops a formatted alert payload into the background dispatch queue. — **Corrected:** the real value is lowercase `"critical"` (see §3's Accountability Rule correction above); verified with `severity: "critical"` and `"severe"` (`test_ac2_critical_incident_write_drops_alert_into_queue`), and confirmed `"minor"` does *not* fire (`test_minor_incident_does_not_fire_an_alert`).
3. Given the synthesize node drafts a response claiming "Repair cost $500" but the scratchpad says "$50", when the truth checker runs, then it detects the hallucinated number and forces a rewrite before the user sees it. — Verified end-to-end (`test_ac3_hallucinated_number_forces_a_synthesize_rewrite`): a scripted fact-checker LLM returns "YES" for the $500 draft, the graph loops back to `synthesize`, a corrected "$50" draft passes on the second check, and that corrected text is what the user actually receives.

---

## Implementation Notes (post-execution)

- **`cache.py`:** each `ExactCacheBackend` entry is now tagged with a `f"{tool_name}:{organization_id}"` namespace at write time; `invalidate_namespace(tool_name, organization_id)` purges that namespace plus `insights:{organization_id}` unconditionally (Insights aggregates fleet-wide data touching every other agent's writes — this generalizes AC 1's own "fuel AND insights" example to every write-capable agent, not just fuel). `graph.py`'s `execute_tool` calls it right after a successful (`status="done"`) call where `_is_read_only_call` is `False` — reusing the exact same read/write classification the cache pre-hook already established, not a second one.
- **`orchestrator/webhooks.py`:** new module, `AlertDispatcher` mirrors `FleetLiveObserver`'s shape exactly (`attach_queue`/`run_worker` for async draining, a sync `evaluate_and_queue(agent_name, raw_result, organization_id)` entry point `execute_tool` calls directly after every successful tool result, not just writes — a low-stock *query* result deserves the same alert a restock write would trigger). Internally exception-safe (never raises), matching every other optional hook in this codebase.
- **`orchestrator/fact_check.py`:** new module, `check_response_against_scratchpad(llm, scratchpad_text, final_response) -> bool`, fails open on any exception. A new `fact_check` graph node sits between `synthesize` and `END`; `OrchestratorDeps.fact_checker_llm` defaults to `None` (deliberately *not* auto-constructed the way the main `llm` is — a fact-checker is an explicit opt-in, not a silent extra LLM call on every turn), in which case the node is a pure pass-through. `OrchestratorState._fact_check_retries`/`_fact_check_warning` are both declared on the `TypedDict` (the same lesson `grand-orchestrator.md` learned the hard way: an undeclared key a node returns is silently dropped by LangGraph, not an error) and reset to `0`/`None` at the start of every user turn in `session.py`'s `run()`, so a fact-check loop from a prior turn can never carry over and silently disable the guardrail on the next one.
- **Backward compatibility:** `cache`, `webhooks`, and `fact_checker_llm` all default to `None`/absent behavior on `OrchestratorDeps`, the same additive-injection convention established for `observer` in `fleet-live-observer.md` and `cache` in `execution-pre_hooks.md` — all 320 pre-existing tests pass unmodified.

## Test coverage

29 new tests (349 total in `ai_agents/`): `test_cache.py` (namespace invalidation, 3 new), `test_webhooks.py` (13, rule evaluation + async dispatch), `test_fact_check.py` (5, the checker helper in isolation) plus `test_orchestrator_posthooks_integration.py` (8, all three hooks verified through a real, scripted `OrchestratorSession` run, including that a read never triggers invalidation, that no-webhooks/no-fact-checker reproduces the pre-post-hooks baseline, and that the fact-check retry loop is bounded and still returns a response). All 320 pre-existing tests pass unmodified.
