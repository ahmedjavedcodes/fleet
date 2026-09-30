# Spec: Execution Pre-Hooks (Security, Normalization, Caching)

*Verified and executed directly (no separate plan document existed). Two real corrections found: one in the spec's own acceptance-criterion example (a substring-matching bug baked into its own config default), and one factual claim (AC 2's specific example) that doesn't hold given how the orchestrator's tool schemas are actually typed. Two infrastructure gaps (Redis, embeddings) resolved the same way as every prior "assumed infra that doesn't exist" finding in this codebase — a real, tested default plus an honest, documented gap, not a fake.*

## Problem Statement

Unchanged — three real inefficiencies (prompt injection exposure, retry-triggering formatting noise, redundant reads) ahead of expensive LLM/sub-agent work. Confirmed real and worth solving by building all three.

## §2 Input Security & Guardrail Pre-Hook — implemented, with a correction to the spec's own example

`orchestrator/security.py`'s `scan_user_input()`, called at the very top of `OrchestratorSession.run()`, before anything else — a violation returns `TurnResult(status="halted", ...)` without `build_orchestrator_graph` or the LLM ever being touched (verified: `llm.invoke_calls == 0`).

**Correction:** the spec's own `SecurityConfig.blocked_phrases` default (`"ignore previous"`) is a literal substring the spec's *own* AC 1 example text doesn't contain — `"ignore all previous instructions"` has `"all"` sitting between the two words, so `"ignore previous" in "ignore all previous instructions".lower()` is `False`. A naive substring check, implemented exactly as the config's shape implies, would fail the spec's own acceptance test. Regex patterns tolerant of words in between (`ignore\s+(all\s+)?...previous...instructions`) are the real detection mechanism; `blocked_phrases` remains as a literal supplementary layer for phrases where exact substring matching is genuinely what's wanted (`"drop table"`, `"bypass"`).

Domain bounding is a keyword-allowlist heuristic spanning every sub-agent's domain (vehicles, drivers, fuel, maintenance, parts, incidents, assignments, dashboards, HR/logistics terms) — broad enough that a real fleet question essentially never false-positives, at the cost of also rejecting plain chit-chat ("hi", "thanks") as off-topic. That's a deliberate reading of "reject queries completely unrelated to fleet operations," not a bug — flagging it as the one UX trade-off worth knowing about.

**Semantic LLM guard (`SecurityConfig.enable_llm_guard`, on by default, active when `OrchestratorDeps.guard_llm` is set).** After the static checks (length, blocked phrases, injection regexes — unchanged, and they never spend an LLM call), a small guard model classifies the message as JSON `{"is_safe", "is_fleet_related", "reason"}`. `is_safe=false` → the generic refusal; `is_fleet_related=false` (waived when a photo is attached) → `OFF_TOPIC_MESSAGE`. The whole call is capped at `llm_guard_timeout_seconds` (0.8 s); on timeout, provider error or unusable JSON the keyword allowlist above decides instead, so the guard can only improve on the heuristic, never break chat. The guard chain (`core.llm_failover.get_guard_chat_model`) is Tier 0 local Ollama if running, then Groq `openai/gpt-oss-safeguard-20b` (`GUARD_MODEL`), with no paid tier; `LLM_GUARD=off` disables it in the server. `scan_user_input` is `async`; `OrchestratorSession.run` stays synchronous and awaits it through a small bridge.

## §3 Parameter Normalization Pre-Hook — implemented, with a correction to AC 2's premise

`orchestrator/normalization.py`'s `normalize_tool_args()`, called in `execute_tool` immediately before `validate_tool_args` (`graph.py`), recursively over nested dicts (not just top-level fields).

**Correction:** AC 2 claims normalizing `vehicle_plate` "prevent[s] a `ToolValidationError`" — but none of the six orchestrator `TOOL_SCHEMAS` actually validates `vehicle_plate` strictly. It lives nested inside a loosely-typed `dict[str, Any]` field (`AssignmentToolInput.assign_request`), which has no per-key validation at all — `{"vehicle_plate": "xyz-999 "}` would pass Pydantic validation completely unchanged today, normalized or not. Normalization still has real, provable value: it prevents `Literal`-enum case mismatches (`query_entity="Vehicles"` would genuinely fail validation) and, more importantly, produces cleaner data for the sub-agent's own downstream resolution logic — reducing entity-lookup misses, not `ToolValidationError`s specifically, for the fields the spec names. Tests verify the actual behavior (values get normalized, correctly, recursively) rather than the spec's unverifiable specific claim.

**A latent bug found while implementing date normalization, not fixed here:** `mcp_server/assignment_tools.py`'s `get_vehicle_assignment_history_tool(target_date: date | None)` calls `target_date.isoformat()`, but the orchestrator's `AssignmentToolInput.query_target_date` (and `AssignmentAgentState.query_target_date`) both type it as a plain `str`. If `query_target_date` is ever populated through the orchestrator, this crashes with `AttributeError: 'str' object has no attribute 'isoformat'` — pre-existing, untested until this pass, and outside this task's scope to fix (same treatment as the Fuel Agent's `Driver.id`/`User.id` bug found earlier: flagged here and in `prompts.md`, not silently patched on this branch).

## §4 Semantic & Exact Cache Lookup Pre-Hook — Tier 1 real, Tier 2 an honest stub

`orchestrator/cache.py`'s `ExecutionCache`, checked in `execute_tool` right after validation succeeds, before `runner.run` — a hit appends the cached observation to the scratchpad and `continue`s the loop, **entirely bypassing `runner.run`** (verified: `runner.run_calls` stays empty on a cache hit).

**Two real infrastructure gaps, resolved rather than faked:**
- **Tier 1** ("a fast in-memory store (e.g., Redis)"): no Redis dependency or service exists anywhere in this project (checked `pyproject.toml`, `docker-compose.yml`). "e.g." makes Redis an example, not a requirement — `ExactCacheBackend` is a real, working in-process `dict` + TTL store, which genuinely *is* a fast in-memory store, swappable for a Redis-backed implementation later via the same `get`/`set` interface.
- **Tier 2** (semantic match via embeddings + Pinecone/FAISS): no embedding-generation pipeline exists anywhere in this codebase — `memory/vector_store.py`'s own `upsert_memory`/`query_memory` require a *pre-computed* `embedding: list[float]`; nothing computes one, and no embedding provider is configured. Faking "semantic similarity" with a crude token-overlap heuristic would risk a false cache hit across two *different* vehicles or drivers — worse than no Tier 2 at all. `NullSemanticCacheBackend` is an honest, always-miss no-op; `SemanticCacheBackend` is a real `Protocol` ready for whoever wires up an embedding provider.

**Two design decisions beyond the spec's literal text:**
- **Class, not a bare function.** The spec's Integration Blueprint sketches `check_cache(tool_name, validated_args, org_id)` as a plain function, but a stateless function can't hold the TTL store across hops/turns without a hidden module-level global — which would leak cache entries between unrelated sessions/orgs in the same process. `ExecutionCache` is held on `OrchestratorDeps`, the same DI pattern as `SubAgentRunner`/`FleetLiveObserver`.
- **Only successful (`"done"`) results are cached**, never `"halted"` ones. A transient backend failure staying cached for `ttl_seconds` would keep serving a stale failure after the underlying issue clears — the spec doesn't address this, and caching failures is the wrong default.
- **Read/write classification** (`_is_read_only_call` in `graph.py`) is structural, matching each agent's own `classify_intent`: an agent with no mutating nodes at all (`insights`) is always read-only; otherwise, a call is read-only iff none of that agent's write-triggering fields (`assign_request`, `terminate_request`, `document_type`, `document_text`, `trip_fields`, `provided_fields`) are populated. `audit_target` (Accountability's trip-audit) is deliberately *not* a write indicator — it never calls a mutating node.

## Integration Blueprint — implemented as specced, with the class-vs-function note above

- `orchestrator/security.py`: as specced.
- `orchestrator/normalization.py`: as specced (a dict of field-name → callable, not literally lambdas, for readability/testability).
- `orchestrator/cache.py`: `ExecutionCache.check`/`.store` replace the sketched bare `check_cache` function; same call sites, same bypass behavior.

## Acceptance Criteria — verified, two with corrected premises noted above

1. **Given** `"ignore all previous instructions"`, **when** `OrchestratorSession.run` is called, **then** the security hook halts immediately, logs the attempt (`logging.getLogger("fleet.security")`), and returns a rejection — verified with `llm.invoke_calls == 0`.
2. **Given** `{"vehicle_plate": "xyz-999 "}` (at the real nesting depth this value actually occurs at), **when** the tool executes, **then** normalization converts it to `"XYZ-999"` before validation — verified directly, without the spec's unverifiable "prevents a ToolValidationError" claim (see §3 correction).
3. **Given** an identical read-only `query_entity="dashboard_summary"` call across two separate session turns, **when** the second executes, **then** the exact-cache hook returns the first turn's observation and `runner.run` is never called for the second — verified end-to-end through a real `OrchestratorSession`.

## Test coverage

41 new tests (320 total in `ai_agents/`): `test_security.py`, `test_normalization.py`, `test_cache.py` (unit tests per module) plus `test_orchestrator_prehooks_integration.py` (all three hooks verified through a real, scripted `OrchestratorSession` run — including that a cache-enabled tool's *write* path is never served from cache, and that disabling the cache entirely reproduces the pre-hook baseline behavior). All 279 pre-existing tests still pass unchanged — `cache` defaults to `None` on `OrchestratorDeps`, same additive pattern as `observer`.
