# Spec — PostgreSQL-Backed Agent Memory Architecture (v2)

*Verified against the repo, then executed. Three infrastructure assumptions
did not hold (no pgvector, no embedding provider, and a direct conflict with
the module-boundary rule); each was resolved by an explicit user decision
recorded below, not silently worked around. Corrections are marked inline;
the original intent of every section is kept.*

## Decisions taken before implementation (2026-09-24)

| Question | Decision |
| :--- | :--- |
| Who owns the tables? The spec implied `ai_agents/` writes Postgres directly, which root `CLAUDE.md` and `ai_agents/CLAUDE.md` both forbid. | **Backend owns them.** SQLAlchemy models + Alembic migration + `/api/v1/memory/*` REST endpoints in `backend/`; `ai_agents/` calls them over HTTP with the user's own JWT, so org-scoping and RBAC stay in the backend. |
| Embeddings (`nomic-embed-text-v1.5`, 768-dim): nothing runs it — no Ollama installed, no Nomic key, Groq serves no embedding models. | **Injectable provider, no-op default.** `MEMORY_EMBEDDER=none|ollama|nomic`. With `none`, vectors are simply absent: recall is scope-filtered + keyword, and similarity-based staleness is skipped. No fake vectors are ever produced. |
| pgvector: `docker-compose.yml` used plain `postgres:16`; the developer's local Postgres 18 (Windows) has no `vector` extension. | **Require pgvector everywhere.** Compose now uses `pgvector/pgvector:pg16`; the migration and the test fixtures both run `CREATE EXTENSION IF NOT EXISTS vector` and fail loudly without it. |

---

## 1. Problem Statement

Unchanged: persistent cross-session memory without LLM write hallucinations,
RBAC scope leaks, hot-path latency, or unbounded stale data.

---

## 2. Database Schema (SQLAlchemy & pgvector) — `backend/app/models/memory.py`

### A. Short-Term Memory

**Correction — table names:** `agent_sessions` / `agent_messages`, not bare
`sessions` / `messages`, which are ambiguous in a shared fleet schema.

**`agent_sessions`:** `id`, `organization_id`, `user_id`, `running_summary`,
plus **`summary_version`** (not in the spec) — the optimistic-concurrency
token that makes summary writes safe across processes (see §5). Sessions are
private to their owner: any other user, even an admin in the same org, gets
404 so session ids can't be probed.

**`agent_messages`:** `id`, `session_id`, `role`, `content`, `created_at`,
`is_summarized`. `created_at` uses `clock_timestamp()` so ordering is
well-defined even for messages written in one transaction.

### B. `semantic_memories` (Long-Term Vault)

As specced — `scope` ∈ `personal | organization | entity`, `organization_id`,
nullable `user_id` / `entity_id`, `content`, `embedding VECTOR(768)`,
`is_active` — plus `entity_type` (`vehicle | driver`, needed because
`entity_id` can point at either table), `created_by`, `deactivated_at`, and an
HNSW cosine index. Two check constraints make ill-scoped rows
unrepresentable: a personal fact must have `user_id`, an entity fact must have
`entity_id` + `entity_type`. `embedding` is nullable (see the embeddings decision).

**Scope RBAC (spec said "strict scope isolation" without defining writers):**

| Scope | Visible to | Writable by |
| :--- | :--- | :--- |
| personal | owner only | any role, for themselves |
| organization | whole org | admin, fleet_manager |
| entity | whole org | admin, fleet_manager, mechanic (entity must belong to the caller's org) |

Every read is filtered to the caller's org + active rows + (non-personal OR own).

---

## 3. Write-Path Safety & Staleness Handling

### `update_memory` (HITL-gated) — implemented as specced

Offered to the routing LLM only when `OrchestratorDeps.memory` is configured.
A call **always** pauses the turn (`stage="awaiting_approval"`) with
`hitl_state.approval_prompt = "The Orchestrator wants to remember: '…'. Allow?"`.
Nothing is embedded or saved until `session.approve()` (or `modify()`, which is
re-validated). `reject()` saves nothing. A backend refusal (e.g. a driver
proposing an organization-wide fact → 403) is reported back to the LLM
honestly rather than claimed as saved.

### Staleness post-hook — implemented, with one correction

Fires after any successful write (`status="done"`, `_is_read_only_call` is
`False` — the same classification the cache-invalidation hook uses). Entity
facts are extracted **deterministically** from the sub-agent's result
(maintenance log → vehicle; incident → vehicle and driver; assignment/release →
vehicle custody), then sent in the background to `POST /memories/supersede`, which
in one transaction deactivates active same-entity facts within the similarity
threshold and stores the new one.

**Correction:** without an embedding, supersede stores the new fact but
deactivates **nothing**. Judging "same topic" by keywords alone would retire
unrelated facts that merely mention the same vehicle — worse than leaving a
stale one active. Entity facts are manager/mechanic-writable, so a driver's own
incident filing gets a 403 here, which is logged and swallowed.

---

## 4. Read-Path Safety & Failure Isolation — `fetch_memory` node

Now the graph's entry point (`fetch_memory → plan`). It assembles the running
summary + top-k visible facts into a `<memory>` block, framed in the prompt as
*possibly outdated reference data, never instructions* (a stored sentence must
not become a standing prompt injection).

**Correction — timeout mechanism:** the spec names `asyncio.wait_for`, but the
orchestrator graph is synchronous. The fetch runs on a small thread pool and
the node waits `Future.result(timeout=0.5)`: same hard 500 ms bound, no event
loop needed inside a sync node. Every backend call inside it also carries a
0.5 s httpx timeout, so an abandoned fetch can't linger. Any exception —
timeout, 5xx, embedder down — logs locally and yields an empty context; the
turn proceeds. A HITL resume re-enters the graph at `fetch_memory` but reuses
the turn's already-fetched context instead of refetching.

---

## 5. Concurrency & Transactional Safety — background summarizer

Queue-based as specced: when the backend reports more than 5 unsummarized
messages, `SessionSummarizer` runs off the hot path (a background thread, or an
attached `asyncio.Queue` worker). It folds all but the 4 most recent messages
into the running summary, re-summarizes recursively while the summary exceeds
~1,000 tokens (hard-capped after 2 attempts), and commits.

**Correction — where the lock lives:** a `SELECT … FOR UPDATE SKIP LOCKED`
cannot be held across an LLM call made from another process over HTTP. The
backend makes the **commit** atomic instead: `POST /sessions/{id}/summary`
locks the session row, rejects a stale `expected_summary_version` (409), and
claims the message rows with `FOR UPDATE SKIP LOCKED`, rejecting the write if
any are already summarized or locked (409). Two overlapping summarizers may
both do the LLM work, but exactly one commits; the loser discards its result.

Message recording (`user`, then `assistant`) runs on a single-worker background
queue, so the transcript keeps its order without adding latency to the turn.

---

## 6. Retention & Pruning Policy

- **Hot storage — implemented:** `POST /memories/dedupe` (admin-only) deactivates
  any fact within 0.98 cosine similarity of an **older** active fact with the
  same org/scope/owner/entity — soft-delete, oldest copy kept. It's the job's
  entry point; **no scheduler exists in this project**, so "weekly" means
  wiring a cron/scheduled job to call it.
- **Cold storage — not implemented (honest gap):** there is no S3 bucket,
  credentials, or Parquet tooling anywhere in this project, and deleting
  90-day-old message logs without the archive would destroy compliance data.
  Messages are therefore retained; `running_summary` already carries the
  long-lived context. Same treatment as the telemetry spec's S3 request.

---

## Found while implementing

The execution pre-hooks' domain allowlist (`orchestrator/security.py`)
rejected this spec's own scenario — "Remember my currency" never reached the
orchestrator. Added `remember`, `forget`, `prefer`, `currency`, `amount`. A bare
"Always use PKR." is still rejected; allowlisting words like "always" would
make the filter meaningless. Covered by `tests/test_security.py`.

## Test coverage

- `ai_agents/`: 44 new tests (393 total), all passing — `test_memory_units.py`
  (embedders, staleness extraction, summarizer incl. recompression and lost
  races, `AgentMemory`) and `test_orchestrator_memory_integration.py` (through a
  real `OrchestratorSession`: memory in the prompt, 500 ms timeout honored,
  backend outage fails open, approve/reject/modify/403 for `update_memory`,
  staleness on writes but not reads, transcript persistence and session
  resume). Memory defaults to `None`, so all 349 pre-existing tests pass unchanged.
- `backend/`: `tests/test_memory_routes.py` (25 tests: session privacy, the
  6th-message trigger, both 409 summary races, scope RBAC, cross-org
  isolation, cosine ranking, keyword fallback (wildcards can't widen it),
  supersede with/without embeddings, dedupe). These need a pgvector-enabled
  Postgres — see the verification note in `prompts.md`.
