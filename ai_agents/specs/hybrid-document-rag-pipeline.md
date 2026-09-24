# Feature Specification: Hybrid Document RAG Pipeline (V2 Hardened)

**Feature Type:** Secondary AI feature added (e.g., RAG).

> **Implementation status (2026-09-24): executed, verified live** against real
> Pinecone (a `fleet-documents` dotproduct index, created alongside the untouched
> `fleet-memory` and `digisinc` indexes). Where the code differs from the text
> below, a **Correction** note says why. Architecture as built:
>
> - **The backend owns ingestion and retrieval** (`backend/app/services/document_*.py`,
>   `/api/v1/documents/*`). `ai_agents/` only calls search, through the new
>   orchestrator tool `search_documents`. This is the same boundary as agent memory:
>   the backend verifies the JWT before building any tenant or role filter.
> - **Postgres is the system of record.** `documents` (which also serves as the ingestion
>   lease) and `document_chunks` (the text) live there. Pinecone gets vectors plus filter
>   metadata only, never `chunk_text`. Every hit is re-checked against Postgres
>   (org, the role's allowed types, `ready` status, current version) before it is returned.
> - **No Redis, torch, `pinecone-text` or `langchain_experimental` exist here.** Each is
>   replaced by a real, tested equivalent, listed in the corrections below.

**Primary Objective:** Enable the Grand Orchestrator and sub-agents to accurately and securely query unstructured operational documents (maintenance manuals, supplier invoices, policy PDFs) using semantic meaning and exact keyword matching, protected by multi-layered security and caching.

---

## 1. Access Control, Concurrency & Lifecycle

### 1.1 RBAC Boundary Enforcement

- **Ingestion Route (`POST /api/v1/documents/upload`):** Strictly gated at the API layer to `admin` and `fleet_manager` roles.
- **Retrieval Route (`POST /api/v1/documents/search`):** Globally accessible, but strictly scoped via backend-injected Pinecone metadata filters based on the executing user's role.

**Role-to-Document-Type Mapping Matrix:**

| Role | Permitted `document_type` Values |
| --- | --- |
| **admin** | `manual`, `policy`, `supplier_invoice`, `incident_report`, `legal` |
| **fleet_manager** | `manual`, `policy`, `supplier_invoice`, `incident_report` |
| **mechanic** | `manual`, `policy`, `incident_report` (filtered by assigned `vehicle_id`) |
| **driver** | `manual`, `policy` |

**Correction — mechanic:** "filtered by assigned `vehicle_id`" can't be evaluated,
because mechanics have no vehicle assignment in this data model (assignments are
driver ↔ vehicle only, and maintenance logs record the mechanic as free text). Showing
incident reports unfiltered would be a leak, so they are **withheld from mechanics**;
mechanics see `manual` and `policy`. Documents can still be tagged with a `vehicle_id`
at upload, ready for when a mechanic-assignment concept exists. Requested
`document_types` are always intersected with the role's allowed set.

### 1.2 Versioning & Concurrency Locks

To prevent RAG index corruption from concurrent duplicate uploads and stale vector pollution:

1. **Concurrency Lock:** The ingestion endpoint wraps the transaction in a Redis distributed lock:
   ```python
   redis.set(f"lock:doc_ingest:{document_id}", "1", nx=True, ex=300)
   ```
   Failure to acquire returns `429 Too Many Requests`.
   - **Correction:** no Redis exists in this project. The lock is a **Postgres row
     lease**: the `documents` row is locked `FOR UPDATE`, and a row still `processing`
     whose `processing_started_at` is under 300 s old returns 429. That matches
     `nx=True, ex=300`, including expiry of a crashed worker's lease.
2. **Deterministic ID:** A `document_id` is generated via SHA-256 hash of `filename` + `document_type`.
   - **Correction:** the hash also includes `organization_id`. Without it, two tenants
     uploading `manual.pdf` would get the same document id.
   - *Added:* vector ids carry the document **version** (`<org>#<doc>#v<n>#<chunk>`), and
     hits whose version isn't current are discarded. A stale ingestion that outlives its
     lease and finishes after a newer upload can then never surface. It also re-checks
     the version before committing its chunks.
3. **Synchronous Pre-Purge:** Before new vectors are processed, a blocking Pinecone deletion executes:
   ```python
   index.delete(
       filter={"document_id": doc_id, "organization_id": org_id},
       namespace="rag_documents",
   )
   ```
   - As specced. If Pinecone is unreachable the upload is **rejected with a 503**, since
     stale vectors can't be ruled out. Found live earlier: a delete on a never-written
     namespace returns 404, which the adapter treats as a no-op.

---

## 2. Ingestion & Extraction Architecture

### 2.1 Spatial Sequencing (PyMuPDF)

Standard text extraction destroys PDF layout logic. This pipeline relies on spatial coordinates (`x0, y0, x1, y1`):

- Tables and text blocks are extracted independently.
- **Table Context Expansion:** Table bounding boxes are expanded vertically by 60 pixels (`max(0, y0 - 60)`) to natively capture the preceding header or introductory paragraph.
- **Deduplication:** Text blocks sharing overlapping coordinates with table bounding boxes are discarded.
- **Chronological Assembly:** All extracted blocks are merged and dynamically sorted by their top vertical coordinate (`y0`) to recreate the exact reading sequence.

*As built* (PyMuPDF 1.28, `page.find_tables()` + `get_text("blocks")`):
- **Correction:** PDF coordinates are **points**, not pixels, so the expansion is 60 pt.
- Blocks that overlap the expanded area above a table become that table's **context**
  instead of being discarded, so the heading the expansion was meant to capture is kept
  exactly once.
- Sorting is by (page, y0). Plain-text uploads are split into paragraphs.
- Scanned/image-only PDFs produce no text and fail with a clear error; OCR is out of scope.

### 2.2 Cost-Bounded Table Summarization

Raw markdown tables degrade semantic vector similarity.

- Tables plus their expanded context are routed to a fast LLM for a 3–4 sentence summarization.
- **Cost Ceiling:** Summarization is strictly capped at **15 tables per document**. Excess tables degrade gracefully to raw Markdown insertion.
- **Failure Isolation:** Summarization executes on a background worker thread with a 3-retry exponential backoff. Persistent failures fall back to Markdown and log to a PostgreSQL Dead-Letter Queue (DLQ).
  - *As built:* the whole ingestion runs on a background worker, and upload returns
    **202** with a `processing` document to poll. There are 3 attempts per table (0 s,
    1 s, 2 s backoff). Failures go to `document_ingest_failures` and the table is indexed
    as Markdown. The LLM is Groq over plain httpx (no LangChain in the backend). With no
    `GROQ_API_KEY`, every table uses the Markdown fallback.
  - **Correction:** a chunk stores the summary together with the exact table, but only
    the **summary is embedded**. The spec's reason for summarizing is that raw tables
    embed badly, yet the agent still needs the exact figures to cite.

### 2.3 Chunking & Dual-Vector Generation

- **Semantic Boundary Splitting:** The ordered text array is processed by a LangChain `SemanticChunker` to break at natural thematic transitions.
- **Dual Encoding:** Each chunk generates a Dense vector (`nomic-embed-text-v1.5`, 768-dim) and a Sparse lexical vector (`pinecone-text` SPLADE/BM25).

**Corrections (all three verified live):**
- **Chunking:** the same algorithm as `SemanticChunker` (95th-percentile breakpoints on
  adjacent-sentence cosine distance, plus a 2,000-character cap), implemented in about
  40 lines rather than adding `langchain_experimental` + LangChain to the backend.
  A table is always exactly one chunk.
- **Dense:** Pinecone Inference `llama-text-embed-v2` at 768 dims. That's the same key
  and dimension as agent memory; no nomic runtime exists here.
- **Sparse:** Pinecone Inference `pinecone-sparse-english-v0`, a hosted learned-sparse
  lexical model. It fills the SPLADE/BM25 role with no torch and no BM25 corpus fitting.
- **Hybrid needs a `dotproduct` index**, so documents live in their own `fleet-documents`
  index (the memory index is cosine). `scripts/create_pinecone_index.py` creates both.
- **Upsertion:** Both vectors are combined and upserted to the Pinecone `rag_documents` namespace with strict metadata:
  ```json
  {
    "organization_id": "...",
    "document_id": "...",
    "document_type": "...",
    "chunk_text": "..."
  }
  ```

---

## 3. Retrieval, Caching & Cross-Encoder Reranking

When a sub-agent executes the `search_documents` tool, the retrieval pipeline executes a three-stage resolution:

1. **Stage 1: Tier 1 Semantic Cache (Redis)**
   - The user's query is checked against the Redis cache. If a `> 0.95` semantic match is found, the system instantly serves the pre-synthesized answer and cited chunks, bypassing Pinecone and LLM generation entirely.
   - **Corrections:**
     - No Redis exists, so the cache is **in-process** (per backend worker, 300 s TTL).
     - **Security bug in the spec:** the cache key had no tenant or role component, so a
       fleet manager's cached invoice answer would have been served to a driver or to
       another org. The key is now (org, the caller's allowed document types).
     - The search API returns cited chunks; the answer is synthesized by the
       orchestrator, so chunks are what gets cached.
     - The cache is invalidated when a document in the org finishes ingesting or is deleted.
     - **Empty results are never cached.** Right after an upload Pinecone may not have the
       vectors yet, and a cached "nothing found" would hide the new document for the TTL.

2. **Stage 2: Convex Hybrid Search (Pinecone)**
   - If no cache hit occurs, the query is embedded into sparse and dense formats.
   - Pinecone is queried using a convex combination weight of `alpha=0.5` to retrieve a broad net of `top_k=10` chunks.
   - As specced: the dense part is scaled by α and the sparse part by 1−α. The filter is
     org-pinned and restricted to the role's document types, and every Pinecone call
     still goes through `OrgScopeGuard`.

3. **Stage 3: Precision Scoring (bge-reranker-base)**
   - The cross-encoder evaluates the logical relevance between the query and the 10 chunks.
   - **Hard Threshold:** Chunks scoring `< 0.65` are instantly discarded.
   - The system retains a maximum of the **top 3** chunks. If zero chunks clear the threshold, the tool explicitly returns a null payload to prevent forced hallucination.
   - **Correction — model and threshold, calibrated live.** `bge-reranker-base` needs a
     local torch model. The hosted `bge-reranker-v2-m3` (its successor) is used instead,
     and the spec's 0.65 threshold is wrong for it:

     | Query | Correct passage | Best wrong passage |
     | --- | --- | --- |
     | "How often should brake pads be changed?" | **0.576** | 0.002 |
     | "brake pad replacement interval Hilux" | 0.997 | 0.010 |
     | "what did we pay for brake pads" | 0.711 | 0.001 |
     | "when must fuel receipts be submitted" | 0.995 | 0.000 |
     | "what oil does the engine take" | 0.941 | 0.000 |
     | "who won the football match" (off-topic) | — | 0.000 |
     | Live end-to-end, real PDF: "How often do brake pads need replacing?" | **0.541** | — |

     With 0.65, two of these correct answers would have returned a null payload. The
     threshold is **0.30** (`RAG_RERANK_THRESHOLD`), inside a wide gap on both sides.
     `pinecone-rerank-v0` separated worse, and Cohere isn't enabled on this project.
   - If the reranker or Pinecone fails mid-search, the API returns a **503**, never
     unreranked results. Skipping precision scoring would hand the LLM exactly the
     low-relevance context the threshold exists to exclude.

---

## 4. Security Guardrails & Continuous Evaluation

### 4.1 Prompt Injection Defense (Defense-in-Depth)

External documents represent an untrusted attack surface.

- **Heuristic Pre-Scan:** Retrieved chunks undergo a lightweight signature scan for jailbreak phrasing. This is a cheap first-pass sieve, not a cryptographic guarantee.
- **XML Sandboxing:** Surviving chunks are strictly wrapped in `<untrusted_document_context>` XML tags before injection into the Orchestrator's prompt.
- **System Directive:** The true structural bulkhead is the Orchestrator's hardcoded system prompt, which explicitly mandates that text within the untrusted XML tags is inert reference data and cannot override system execution paths.

*As built* (`ai_agents/orchestrator/document_context.py`):
- The pre-scan reuses the user-input injection patterns and adds document-specific ones:
  role spoofing (`SYSTEM:`), tag break-out, tool hijacking ("call the X tool"), and
  concealment ("do not tell the user"). Flagged chunks are dropped, and the drop is
  counted in the observation.
- **Correction:** wrapping alone isn't a sandbox. A chunk containing
  `</untrusted_document_context>` would close the tag and continue as if it were prompt
  text. Chunk text and attributes are therefore **XML-escaped** before wrapping, and a
  test bypasses the pre-scan to prove the escaping holds on its own.
- The directive is part of the orchestrator's system prompt. `search_documents` is
  offered only when a retriever is configured (`OrchestratorDeps.documents`). A
  retrieval outage becomes an observation, never a failed turn.
- The execution pre-hooks' domain allowlist would have rejected "What does the manual
  say…?" and "Summarize our overtime policy", so document words were added to it.

### 4.2 RAG Triad Telemetry

To monitor pipeline degradation, an asynchronous LLM-as-a-judge system evaluates a 5% sample of RAG transactions:

| Metric | Target | Evaluation Criteria |
| --- | --- | --- |
| **Context Relevance** | `> 0.85` | Did the reranker select highly applicable chunks, or was it noise? |
| **Faithfulness** | `1.0` | Did the Orchestrator rely *only* on the provided chunks without hallucinating external numbers? |
| **Answer Relevance** | `> 0.90` | Did the final response directly address the user's core intent? |

*As built* (`ai_agents/orchestrator/rag_eval.py`):
- `RagTriadEvaluator`, injected as `OrchestratorDeps.rag_evaluator`, samples 5% of turns
  that actually called `search_documents` (null results included, since faithfulness
  matters most there).
- It runs on a background thread after the answer has been returned. The judge returns
  JSON scores, which are validated and clamped.
- Metrics below target are logged at WARNING. The default sink is local logging, since
  no metrics backend exists here.
- A judge outage or unparseable verdict drops the sample and never affects the user.
