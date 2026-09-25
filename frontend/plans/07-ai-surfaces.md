# 07 — AI Surfaces (scoped)

**Status:** scoped, not detailed. CLAUDE.md §4 already specifies these surfaces in depth.
This plan records **what is actually buildable today**, the prerequisites, and the order of
work. Expand it into a detailed plan before starting.

**Depends on:** 03. (The backend branch merge it used to need is done; see §0.)

**Design note:** the reference has no chat or AI screens (CLAUDE.md §1.1 rows 2–4 are still
TBD). Build these on the existing tokens and primitives, in the reference's language: section
panels, soft-tinted pills, flat cards. Ask for an AI-surface reference before polishing chat.

---

## 0. Prerequisite: merge `backend` → `frontend` ✅ done

**Done 2026-09-25** (merge commit `39083ec`). `origin/backend` and `origin/ai-agents` both
pointed at `22d079f`, so one merge brought in the agent suite, the Grand Orchestrator, agent
memory (Pinecone) and the document RAG pipeline. `backend/app/main.py` now registers
`memory_router` and `documents_router`, and `DocumentType` / `DocumentStatus` exist in
`backend/app/models/enums.py`.

**Before starting §2:** run the new Alembic migrations (agent memory, failed vector jobs,
document RAG tables) and set the new variables in `backend/.env.example` (Pinecone etc.).
Then confirm `/docs` lists `/documents` and `/memory`.

## 1. What exists vs what doesn't

| Surface | Backend today | Frontend approach |
| --- | --- | --- |
| **Documents** (`/documents`) | ✅ Merged into `frontend`: `GET /documents`, `POST /documents/upload` (202, upload roles), `POST /documents/search`, `GET /documents/{id}`, `DELETE /documents/{id}` (upload roles) | **Build it for real.** First AI surface to ship. |
| **Citations** (RAG) | ✅ `DocumentSearchResponse {results: DocumentSearchHit[], cached}` | Build `CitationPill` / hover card / sheet against search results; reuse in chat later. |
| **Chat** (`/chat`) | ❌ No HTTP API. `ai_agents` now has the full Grand Orchestrator (`orchestrator/session.py`, `runner.py`, `ui_interpolation.py`), but still **no web server** (no FastAPI app or SSE endpoint; re-checked after the merge). | Typed adapter `lib/api/chat.ts` → `{ status: "unavailable" }` + `NotAvailableYet`. Build the presentational components (ChatThread, AgentActivity, ApprovalCard) against **typed fixtures in tests and Storybook-like test renders only**, never in production paths. |
| **Chat history** | ⚠️ `/memory` has `POST /sessions`, `GET /sessions/{id}/context`, `POST /sessions/{id}/summary` and memory CRUD, but **no "list my sessions" endpoint** | The conversation side panel needs `GET /memory/sessions` (list). Add it to the backend gaps; until then the panel shows "History will appear here". |
| **Memory admin (DLQ)** | ✅ `GET /memory/vector-jobs/failed`, `POST …/{job_id}/retry` (admin) | Optional admin health view. Out of scope unless requested. |
| **Notifications** (`/notifications`) | ❌ `AlertDispatcher` only logs | Adapter → unavailable. The page shows three tabs (Warnings, Notified Events, Triggers), each with `NotAvailableYet`. The bell stays badge-less (plan 03). |
| **Insights NL search** (`/insights`) | ❌ `query_fleet_data` MCP tool not wired to HTTP | Box routes the question to `/chat` (itself unavailable), or shows "coming soon". **Never** build or run SQL in the browser. |
| **Insights analytics** (`/insights`) | ✅ Dashboard endpoints (A/FM) | Build now: an expanded version of the plan 04 A/FM widgets (fuel trends 24-month, full maintenance calendar with `window_days` picker, fleet-health table with per-signal breakdown and "n/a" for null). Could ship with plan 04/06 since it isn't AI-dependent. |

## 2. Documents: `/documents` (buildable)

**Schemas** (`backend/app/schemas/document.py`):

- `DocumentResponse`:
  - `id, filename, document_type, vehicle_id?, status, version, size_bytes`;
  - `chunk_count, tables_found, tables_summarized, error_message?, created_at, updated_at`.
- `DocumentSearchRequest`: `{ query (3–500 chars), document_types?: DocumentType[] }`.
- `DocumentSearchHit`: `{ document_id, filename, document_type, chunk_index, text, relevance }`.
- `DocumentSearchResponse`: `{ results: DocumentSearchHit[] (≤ 3), cached: boolean }`.
- Enums to add to `lib/schemas/enums.ts`:
  - `DocumentType`: `manual | policy | supplier_invoice | incident_report | legal`;
  - `DocumentStatus`: `processing | ready | failed`.

  Both verified against `backend/app/models/enums.py` after the merge.

**Regions:**

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
states, and delete invalidation.

## 3. Chat: `/chat` (UI only until the API exists)

- **`lib/api/chat.ts`** defines the CLAUDE.md §5.5 contract as zod schemas:
  - SSE events `activity | token | approval_required | citations | done | error`;
  - `hitl_state`, and `status: "awaiting_approval" | "halted" | "done"`;
  - `sendMessage()` returns `{ status: "unavailable" }` today.
- **Page:** `NotAvailableYet` ("The AI assistant is waiting on its chat API"), plus the
  role-based example prompts as **disabled** suggestions so the page communicates intent.
  No fake conversation.
- **Components built and unit-tested now** (rendered only in tests until the API lands):
  - `ChatThread` + `MessageBubble` (react-markdown + remark-gfm, **no rehype-raw**; token
    component map for tables and code with a copy button; links `target="_blank"
    rel="noopener noreferrer"`);
  - `Composer` (Enter sends, Shift+Enter adds a newline; Stop via `AbortController`;
    disabled while an approval is pending);
  - `AgentActivity` (step rows with agent icon, a pulsing/glowing active indicator using
    tokens and honoring reduced motion, a check when done; **text rendered exactly as the
    backend sends it**; agent key → icon map for `foundation`, `fuel`, `maintenance`,
    `accountability`, `insights`, `assignment`, `search_documents`, `update_memory`);
  - `ApprovalCard` (pending action, key `hitl_state.state` fields, `approval_prompt`;
    Approve / Modify (inline, re-validated) / Reject (confirm); **never auto-approve**);
  - `HaltedCard` (warning callout, not an error);
  - "Jump to latest" pill and at-bottom auto-scroll.
- **SSE client:** `lib/api/sse.ts`, a `fetch` + `ReadableStream` parser through the proxy
  (so the cookie auth works; `EventSource` can't send custom headers, but the proxy adds
  them, so either works). Chosen when the API lands.
- **When the API lands:** replace the adapter, move the endpoint from CLAUDE.md §5.5 to §5.4,
  and delete the unavailable path (CLAUDE.md §8).

## 4. Notifications and Insights NL

- **`/notifications`:** tabs (Warnings / Notified Events / Triggers) using the CLAUDE.md §5.5
  mapping. Each tab is `NotAvailableYet` backed by `lib/api/notifications.ts`, which returns
  unavailable. The bell never shows a count.
- **`/insights`:** analytics regions are real (see §1). An NL box above them posts nothing;
  it says "Natural-language questions are coming soon" and offers "Ask in AI Assistant"
  (→ `/chat`).

## 5. Suggested order

1. Merge `backend` → `frontend` (§0).
2. Insights analytics (not AI-dependent; reuses plan 04 components).
3. Documents library + upload + search + citation components.
4. Notifications and chat "not available" pages, plus the chat component library with tests.
5. Wire chat and notifications as their APIs land.

## 6. Backend gaps surfaced here

Add these to [00](00-design-analysis.md) §6:

- `GET /memory/sessions`: list the current user's sessions (for the chat history panel).
- The chat SSE API, the notifications API and the insights NL query (already in CLAUDE.md §5.5).
- CLAUDE.md §5.4 lists `/memory/sessions` as "chat history", but only create/context/summary
  exist. Fix the wording in CLAUDE.md when this phase starts.
