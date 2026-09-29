# 07 — AI Surfaces (scoped)

**Status:** `/chat` shipped for real 2026-09-29 — `ai_agents/server.py` is a new HTTP/SSE
server wrapping `orchestrator.session.OrchestratorSession` directly (a genuine multi-agent
run against the real backend, not mock data), proxied into `frontend` via
`api/proxy-agents/[...path]`. See CLAUDE.md §4's "Implementation note" for the three ways
the first cut is simpler than that section's target design (no conversation list, one
coarse activity step instead of a per-hop trace, word-chunked rather than token-level
streaming). `/insights` (analytics only) also shipped live. `/documents` and
`/notifications` remain UI-only per §2/§4 below — CLAUDE.md §4 already specifies the full
target design for all of these in depth.

**Depends on:** 03.

**Strict constraint (added 2026-09-29): the `backend` branch is never merged into
`frontend`.** They stay permanently separate. `backend`'s agents/memory/document-RAG
pipelines — and therefore `/documents` and `/memory` — do not exist on this branch's backend
instance and are not assumed to arrive by a later phase. Any future plan that wants them
back needs its own explicit decision, not a resumption of this one.

**Design note:** the reference has no chat or AI screens (CLAUDE.md §1.1 rows 2–4 are still
TBD). Build these on the existing tokens and primitives, in the reference's language: section
panels, soft-tinted pills, flat cards. Ask for an AI-surface reference before polishing chat.

---

## 1. What exists vs what doesn't

| Surface | Backend today | Frontend approach |
| --- | --- | --- |
| **Documents** (`/documents`) | ❌ Not on this branch's backend — `backend` is never merged in (see above). `DocumentType`/`DocumentStatus` already exist in `lib/schemas/enums.ts` from plan 01, kept as-is since they cost nothing to keep and the plan may resume later. | **UI only, like chat.** `lib/api/documents.ts` is a typed adapter (zod schemas mirroring the spec below, kept for the day this lands) whose functions all return `{ status: "unavailable" }` — no `fetch` call exists in it at all. The page renders `NotAvailableYet`. The Library table, upload flow and citation pills are built as real components with real props, but the only place they render is unit tests / test fixtures — no production page imports them. |
| **Citations** (RAG) | ❌ Same as Documents. | Build `CitationPill` / hover card / sheet against typed fixture data, tested but not shipped on any live page; reused by chat's design later. |
| **Chat** (`/chat`) | ✅ **Live as of 2026-09-29.** `ai_agents` had the full Grand Orchestrator (`orchestrator/session.py`, `runner.py`) but no web server — `ai_agents/server.py` is new: a FastAPI/SSE app wrapping `OrchestratorSession` (session create, message send, approve/modify/reject), run alongside `backend` on its own port (8100) and proxied into `frontend` via `api/proxy-agents`. | `lib/api/chat.ts` calls the real endpoints; the presentational components (ChatThread, AgentActivity, ApprovalCard, …) are wired into `app/(app)/chat/page.tsx` for real, not just rendered in tests. See CLAUDE.md §4's "Implementation note" for what's simplified vs. the full target design. |
| **Chat history** | ⚠️ `/memory` has `POST /sessions`, `GET /sessions/{id}/context`, `POST /sessions/{id}/summary` and memory CRUD, but **no "list my sessions" endpoint** — and regardless, `memory` isn't wired into `OrchestratorDeps` for this first pass (no Pinecone dependency). | Not built: no conversation side panel. A later pass would need `GET /memory/sessions` (still a genuine backend gap) plus threading `memory=` through `server.py`'s session construction. |
| **Memory admin (DLQ)** | ✅ `GET /memory/vector-jobs/failed`, `POST …/{job_id}/retry` (admin) | Optional admin health view. Out of scope unless requested. |
| **Notifications** (`/notifications`) | ❌ `AlertDispatcher` only logs | Adapter → unavailable. The page shows three tabs (Warnings, Notified Events, Triggers), each with `NotAvailableYet`. The bell stays badge-less (plan 03). |
| **Insights NL search** (`/insights`) | ❌ `query_fleet_data` MCP tool not wired to HTTP | Box routes the question to `/chat` (itself unavailable), or shows "coming soon". **Never** build or run SQL in the browser. |
| **Insights analytics** (`/insights`) | ✅ Dashboard endpoints (A/FM) | Build now: an expanded version of the plan 04 A/FM widgets (fuel trends 24-month, full maintenance calendar with `window_days` picker, fleet-health table with per-signal breakdown and "n/a" for null). Could ship with plan 04/06 since it isn't AI-dependent. |

## 2. Documents: `/documents` (UI only until the API exists)

Same treatment as chat (§3): a typed adapter that always resolves to unavailable, a
`NotAvailableYet` page, and a real component library exercised only in tests. The shapes
below are kept from the original (buildable) version of this plan as the target contract —
useful groundwork for whenever `/documents` actually ships, on this backend or a future
merge — but nothing here is wired to a live `fetch`.

**Schemas** (kept from `backend/app/schemas/document.py` on the `backend` branch, for reference —
not verifiable against *this* backend since it isn't merged in):

- `DocumentResponse`:
  - `id, filename, document_type, vehicle_id?, status, version, size_bytes`;
  - `chunk_count, tables_found, tables_summarized, error_message?, created_at, updated_at`.
- `DocumentSearchRequest`: `{ query (3–500 chars), document_types?: DocumentType[] }`.
- `DocumentSearchHit`: `{ document_id, filename, document_type, chunk_index, text, relevance }`.
- `DocumentSearchResponse`: `{ results: DocumentSearchHit[] (≤ 3), cached: boolean }`.
- Enums to add to `lib/schemas/enums.ts`:
  - `DocumentType`: `manual | policy | supplier_invoice | incident_report | legal`;
  - `DocumentStatus`: `processing | ready | failed`.

  `DocumentType`/`DocumentStatus` are already in `lib/schemas/enums.ts` (plan 01); the rest
  of this file's schemas are new, added to `lib/schemas/document.ts`.

**Regions** (component contracts below — every one of these is driven by props/fixtures in
tests, never by a real request; `lib/api/documents.ts`'s functions are never called from a
page):

1. **Library table:**
   - columns: filename, type badge, vehicle, version, size, status pill (`processing`
     shows an animated dot; reduced motion → static), updated;
   - a type filter limited to `visibleDocumentTypes(role)` (CLAUDE.md §2.1 matrix;
     a UX mirror, not security);
   - Delete (A/FM) → confirm → invalidate the list and **all** search queries.
2. **Upload (A/FM only):**
   - a dropzone with `accept=".pdf,.txt,.md"` plus MIME and size pre-validation;
   - fields: `document_type` and an optional vehicle picker;
   - **Transfer phase:** an `XMLHttpRequest` byte progress bar (`upload.onprogress`),
     through `/api/proxy/documents/upload` (the proxy must stream multipart, which plan 02
     already requires);
   - **Processing phase:** poll `GET /documents/{id}` with `refetchInterval` (2s, backing off
     to 10s), stopping on `ready`/`failed`. Stepped indicator: Extracting → Summarizing
     tables → Embedding → Ready, labeled "indicative";
   - **Result card:** `chunk_count`, `tables_found`, `tables_summarized`, `version`
     (a re-upload of the same filename and type increments it), size, `updated_at`; on
     `failed`, `error_message` + Retry upload;
   - **Error mapping** exactly per CLAUDE.md §4.3 (429 with a countdown-disabled retry, 413,
     415, 422, 404 vehicle, 403, 503), shown inline and never as a toast only.
3. **Search:**
   - `POST /documents/search`, with results rendered as `CitationPill`s plus
     "From: {filename}" plain-text blocks;
   - `cached: true` → a subtle "cached" badge;
   - empty `results` → the designed "The uploaded documents don't cover this" state;
   - a 503 → "Document search is temporarily unavailable" + retry.

**Citation components** (`src/components/ai/`, shared with chat later):

- `CitationPill`: file icon, filename, type badge.
- `CitationHoverCard`: filename, type, chunk number, a relevance meter (0–1, `role="meter"`),
  a ≈300-char snippet with **text-only** query-term highlighting (split and wrap in
  `<mark>`; never HTML injection).
- `CitationSheet`: the full passage as plain text, plus a link to `/documents?id=`.

Passages are untrusted: no markdown rendering of chunk text, no `dangerouslySetInnerHTML`
(CLAUDE.md §4.5).

**Tests:** the upload flow including **429** (countdown), 413/415 pre-validation, polling
stops on ready/failed, the empty search state, the cached badge, `CitationPill` in all
states, and delete invalidation — all against fixture props, since there is no live endpoint
to hit. The `/documents` page itself only has one thing to test: it renders
`NotAvailableYet` and never imports the Library/upload/search components.

## 3. Chat: `/chat` — live (2026-09-29)

The API landed: `ai_agents/server.py`. This section is now what actually shipped, not a
plan for later.

- **`ai_agents/server.py`** (new): FastAPI + `sse-starlette`, in-memory per-process session
  store (`OrchestratorSession` instances keyed by a `uuid4` session id, no persistence —
  restarting the process loses in-flight conversations). Auth: the browser's own
  backend-issued JWT is forwarded as a Bearer token and decoded by
  `tools.auth_context.build_context` — this server never re-authenticates the user itself.
  `POST /api/v1/chat/sessions` (create), `.../messages` (`{message}` → SSE), `.../approve`,
  `.../modify` (`{updates}`), `.../reject`. Every turn runs `OrchestratorSession.run` (or
  `.approve`/`.modify`/`.reject`) in a thread pool, since those calls are synchronous, then
  streams: one `activity` event, the final text chunked word-by-word as `token` events (real
  text, deliberately simplified "typing" presentation — see CLAUDE.md §4's note), then `done`
  or `approval_required`.
  - **Required env:** at minimum `GROQ_API_KEY` (the default `_default_llm()` provider) and
    `BACKEND_API_BASE_URL` (already defaults to `http://localhost:8000`) in `ai_agents/.env`.
    `load_dotenv()` had to be added to `server.py` — **nothing else in this codebase called
    it**, every provider in `core/llm_config.py` reads `os.environ` directly, so it was
    silently relying on the caller's shell already having these exported.
  - **Run it:** `uvicorn server:app --port 8100` (or the updated `ai_agents/Dockerfile`,
    which used to `CMD` a no-op module with no server at all).
- **`frontend/src/app/api/proxy-agents/[...path]/route.ts`** (new): the same
  attach-the-cookie's-JWT-server-side proxy pattern as `api/proxy`, pointed at a new
  `AGENTS_API_BASE_URL` (`lib/env.ts`, defaults to `http://localhost:8100`) instead of the
  main backend's `API_BASE_URL` — a different process/port, so it needed its own route.
- **`lib/schemas/chat.ts`**: rewritten against the *real* `orchestrator/state.py` shapes
  after reading that code directly, not guessed from the spec. In particular `HitlState` is
  `{agent_name, thread_id, tool_name?, pending_node?, state?, approval_prompt?}` — no
  `pending_action` field, and `state` is the paused sub-agent's own state dict, not a status
  enum, unlike this plan's original placeholder schema.
- **`lib/api/chat.ts`**: `sendChatMessage()` creates a session (or reuses one),
  `approveChatAction`/`modifyChatAction`/`rejectChatAction` resume it — each returns an
  `AsyncGenerator<ChatEvent>` parsed and zod-validated frame by frame via `lib/api/sse.ts`.
- **`lib/api/sse.ts`**: a real bug was found and fixed here — `sse-starlette` sends **CRLF**
  (`\r\n\r\n`) frame terminators, not LF. The original LF-only boundary check
  (`buffer.indexOf("\n\n")`) never matched, so every frame buffered forever and got silently
  dropped once the stream closed — no error, just an empty assistant bubble. Caught by
  watching it fail live in a real browser (unit tests alone didn't catch it, since they used
  hand-written LF-only fixtures); fixed by normalizing `\r\n` → `\n` on the whole accumulated
  buffer each read. Two regression tests cover it (`tests/lib/api/sse.test.ts`), including one
  for a `\r\n` split exactly across a chunk boundary.
- **`app/(app)/chat/page.tsx`**: wired for real — `ChatThread` + `Composer` +
  `AgentActivity` + `ApprovalCard` + `HaltedCard`, an `AbortController` per turn so Stop
  actually cancels the fetch, and inline error text on failure. **Not built:** the
  conversation history side panel (§1's "Chat history" row) and role-based disabled example
  prompts from the original UI-only plan — dropped once there was a live composer to use
  instead.
- **Not yet true token-level streaming** — see CLAUDE.md §4's "Implementation note" for why
  (the orchestrator's `run()` is one blocking call) and what a later pass would need to
  change (wire `FleetLiveObserver` into the SSE stream, stream the LLM's own tokens instead
  of chunking a finished response).

## 4. Notifications and Insights NL

- **`/notifications`:** tabs (Warnings / Notified Events / Triggers) using the CLAUDE.md §5.5
  mapping. Each tab is `NotAvailableYet` backed by `lib/api/notifications.ts`, which returns
  unavailable. The bell never shows a count.
- **`/insights`:** analytics regions are real (see §1). An NL box above them posts nothing;
  it says "Natural-language questions are coming soon" and offers "Ask in AI Assistant"
  (→ `/chat`).

## 5. What actually happened, in order

1. Insights analytics — live, not AI-dependent, reuses plan 04 components.
2. Documents library + upload + search + citation components — built and tested, not wired
   (no backend, and none assumed per the constraint at the top of this file).
3. Notifications "not available" tabs, plus the full chat component library, built and
   unit-tested.
4. **`ai_agents/server.py` written and wired live** — the chat component library turned out
   to have a real server to talk to after all (the orchestrator's Python code, just missing
   an HTTP layer), so §3 above stopped being "build for later" and became "build the server
   and wire it now." `/documents` and `/notifications` stay unwired since neither has
   *any* backend code to wrap, live or otherwise.

Still true: wiring `/documents`/`/memory`/a notifications API needs its own decision, not a
resumption of this plan, per the constraint at the top of this file.

## 6. Backend gaps surfaced here

These describe the `backend`-branch APIs this plan targets as a future contract; none of them
exist on this branch's backend and merging `backend` in is explicitly not the plan to get
them (see the constraint at the top of this file):

- `/documents` (library, upload, search) and `/memory` (sessions, chat history) — entire
  routers, not present on this backend at all.
- The chat SSE API and the notifications API (CLAUDE.md §5.5).
- The insights NL query endpoint (`query_fleet_data` not wired to HTTP).
