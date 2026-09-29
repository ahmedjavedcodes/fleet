# 07 — AI Surfaces (scoped)

**Status:** scoped, not detailed. CLAUDE.md §4 already specifies these surfaces in depth.
This plan records **what is actually buildable today**, the prerequisites, and the order of
work. Expand it into a detailed plan before starting.

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
| **Chat** (`/chat`) | ❌ No HTTP API. `ai_agents` now has the full Grand Orchestrator (`orchestrator/session.py`, `runner.py`, `ui_interpolation.py`), but still **no web server** (no FastAPI app or SSE endpoint; re-checked after the merge). | Typed adapter `lib/api/chat.ts` → `{ status: "unavailable" }` + `NotAvailableYet`. Build the presentational components (ChatThread, AgentActivity, ApprovalCard) against **typed fixtures in tests and Storybook-like test renders only**, never in production paths. |
| **Chat history** | ⚠️ `/memory` has `POST /sessions`, `GET /sessions/{id}/context`, `POST /sessions/{id}/summary` and memory CRUD, but **no "list my sessions" endpoint** | The conversation side panel needs `GET /memory/sessions` (list). Add it to the backend gaps; until then the panel shows "History will appear here". |
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

1. Insights analytics (the only live surface; not AI-dependent, reuses plan 04 components).
2. Documents library + upload + search + citation components — built and tested, not wired.
3. Notifications and chat "not available" pages, plus the chat component library with tests.
4. Wire documents, chat and notifications if `/documents`/`/memory`/a chat API/a notifications
   API ever exist on *this* backend — which, per the constraint at the top of this file, is
   not assumed to happen from a `backend` branch merge. Treat it as a fresh decision.

## 6. Backend gaps surfaced here

These describe the `backend`-branch APIs this plan targets as a future contract; none of them
exist on this branch's backend and merging `backend` in is explicitly not the plan to get
them (see the constraint at the top of this file):

- `/documents` (library, upload, search) and `/memory` (sessions, chat history) — entire
  routers, not present on this backend at all.
- The chat SSE API and the notifications API (CLAUDE.md §5.5).
- The insights NL query endpoint (`query_fleet_data` not wired to HTTP).
