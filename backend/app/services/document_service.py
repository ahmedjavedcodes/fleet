"""Hybrid document RAG (hybrid-document-rag-pipeline.md): ingestion lifecycle
and three-stage retrieval.

Architecture, mirroring agent memory: Postgres is the system of record
(documents + document_chunks), Pinecone holds only vectors and filter
metadata, and every Pinecone hit is re-checked against Postgres (org, role's
allowed types, `ready` status, current version) before it is returned.

Deviations from the spec's text, each for a reason recorded in the spec doc:
- No Redis exists: the ingestion lock is a Postgres row lease (a `processing`
  row younger than LEASE_SECONDS -> 429), and the semantic cache is
  in-process, keyed by org AND the caller's allowed document types (the
  spec's cache key had no tenant/role component -- a cross-tenant leak).
- document_id hashes organization_id too; filename+type alone collides
  across tenants.
- Vector ids carry the document version; a late-finishing stale ingestion
  can't overwrite or surface over the current version.
- The mechanic's "assigned vehicle_id" filter can't be evaluated: mechanics
  have no vehicle assignment in this data model (assignments are driver <->
  vehicle only). Incident reports are withheld from mechanics rather than
  shown unfiltered.
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
import uuid
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from fastapi import HTTPException, status
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.document import Document, DocumentChunk, DocumentIngestFailure
from app.models.enums import DocumentStatus, DocumentType, UserRole
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.document_chunking import build_chunks
from app.services.document_extraction import extract_pdf_units, extract_text_units
from app.services.rag_inference import get_rag_inference, hybrid_scale
from app.services.table_summarizer import groq_completion, summarize_tables
from app.services.vector_jobs import VectorJobRunner
from app.services.vector_store import VectorSecurityViolation, get_document_store, org_filter

logger = logging.getLogger("fleet.rag")

LEASE_SECONDS = 300
UPSERT_BATCH = 50
CACHE_TTL_SECONDS = 300
CACHE_SIMILARITY = 0.95

ALLOWED_TYPES_BY_ROLE: dict[UserRole, frozenset[DocumentType]] = {
    UserRole.admin: frozenset(DocumentType),
    UserRole.fleet_manager: frozenset(
        {DocumentType.manual, DocumentType.policy, DocumentType.supplier_invoice, DocumentType.incident_report}
    ),
    UserRole.mechanic: frozenset({DocumentType.manual, DocumentType.policy}),
    UserRole.driver: frozenset({DocumentType.manual, DocumentType.policy}),
}
UPLOAD_ROLES = (UserRole.admin, UserRole.fleet_manager)
SUPPORTED_CONTENT_TYPES = {"application/pdf": "pdf", "text/plain": "text", "text/markdown": "text"}


def allowed_types(user: User) -> frozenset[DocumentType]:
    return ALLOWED_TYPES_BY_ROLE.get(user.role, frozenset())


def document_id_for(organization_id: uuid.UUID, filename: str, document_type: DocumentType) -> uuid.UUID:
    digest = hashlib.sha256(f"{organization_id}\x1f{filename}\x1f{document_type.value}".encode()).digest()
    return uuid.UUID(bytes=digest[:16])


def _vector_id(organization_id, document_id, version: int, chunk_index: int) -> str:
    return f"{organization_id}#{document_id}#v{version}#{chunk_index}"


SEARCH_ATTEMPTS = 4
SEARCH_RETRY_DELAY_SECONDS = 0.5


def _unavailable() -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Document search is not configured")


# --- semantic cache (spec §3 stage 1) ---------------------------------------------


def _cosine(a: list[float], b: list[float]) -> float:
    dot = math.fsum(x * y for x, y in zip(a, b))
    norm = math.sqrt(math.fsum(x * x for x in a)) * math.sqrt(math.fsum(y * y for y in b))
    return dot / norm if norm else 0.0


@dataclass
class _CacheEntry:
    vector: list[float]
    results: list[dict]
    expires_at: float


class DocumentSearchCache:
    """In-process stand-in for the spec's Redis tier. The key includes the
    org AND the caller's allowed document types: a hit for a fleet manager's
    query must never be served to a driver who can't see supplier invoices."""

    def __init__(self, *, ttl_seconds: int = CACHE_TTL_SECONDS, similarity: float = CACHE_SIMILARITY, max_entries: int = 200):
        self.ttl_seconds = ttl_seconds
        self.similarity = similarity
        self.max_entries = max_entries
        self._entries: dict[tuple, list[_CacheEntry]] = {}
        self._lock = threading.Lock()

    def get(self, key: tuple, vector: list[float]) -> list[dict] | None:
        now = time.monotonic()
        with self._lock:
            entries = [e for e in self._entries.get(key, []) if e.expires_at > now]
            self._entries[key] = entries
            best = max(entries, key=lambda e: _cosine(vector, e.vector), default=None)
            if best is not None and _cosine(vector, best.vector) > self.similarity:
                return best.results
        return None

    def put(self, key: tuple, vector: list[float], results: list[dict]) -> None:
        with self._lock:
            entries = self._entries.setdefault(key, [])
            entries.append(_CacheEntry(vector, results, time.monotonic() + self.ttl_seconds))
            del entries[: max(0, len(entries) - self.max_entries)]

    def invalidate_org(self, organization_id: uuid.UUID) -> None:
        with self._lock:
            for key in [k for k in self._entries if k[0] == str(organization_id)]:
                del self._entries[key]


search_cache = DocumentSearchCache()


# --- background plumbing (injectable for tests) -------------------------------------

_executor: Executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="doc-ingest")
_session_factory: Callable[[], Session] | None = None
_runner: VectorJobRunner | None = None


def set_ingest_executor(executor: Executor) -> None:
    global _executor
    _executor = executor


def set_ingest_session_factory(factory: Callable[[], Session] | None) -> None:
    global _session_factory
    _session_factory = factory


def set_document_runner(runner: VectorJobRunner | None) -> None:
    global _runner
    _runner = runner


def _new_session() -> Session:
    if _session_factory is not None:
        return _session_factory()
    from app.core.database import SessionLocal

    return SessionLocal()


def _document_runner() -> VectorJobRunner:
    global _runner
    if _runner is None:
        _runner = VectorJobRunner(store_provider=get_document_store, session_factory=_new_session)
    return _runner


# --- ingestion (spec §1.2, §2) ------------------------------------------------------


def start_ingest(
    db: Session,
    user: User,
    *,
    filename: str,
    content_type: str,
    data: bytes,
    document_type: DocumentType,
    vehicle_id: uuid.UUID | None,
) -> Document:
    """Synchronous part: validate, take the lease, pre-purge old vectors, then
    hand the heavy work (extraction, summarization, embedding) to a background
    worker. Returns the `processing` document; clients poll GET /documents/{id}."""
    settings = get_settings()
    kind = SUPPORTED_CONTENT_TYPES.get((content_type or "").split(";")[0].strip().lower())
    if kind is None:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Only PDF and plain-text documents are supported")
    if not data:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Empty file")
    if len(data) > settings.rag_max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"Max upload is {settings.rag_max_upload_mb} MB")
    if vehicle_id is not None:
        found = db.execute(
            select(Vehicle.id).where(Vehicle.id == vehicle_id, Vehicle.organization_id == user.organization_id, Vehicle.is_deleted.is_(False))
        ).scalar_one_or_none()
        if found is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    store, inference = get_document_store(), get_rag_inference()
    if store is None or inference is None:
        raise _unavailable()

    doc_id = document_id_for(user.organization_id, filename, document_type)
    now = datetime.now(timezone.utc)
    document = db.execute(select(Document).where(Document.id == doc_id).with_for_update()).scalar_one_or_none()
    if document is not None and document.organization_id != user.organization_id:  # sha256 collision guard
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Document id collision")
    if (
        document is not None
        and document.status == DocumentStatus.processing
        and document.processing_started_at is not None
        and now - document.processing_started_at < timedelta(seconds=LEASE_SECONDS)
    ):
        db.rollback()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="This document is already being ingested")

    if document is None:
        document = Document(id=doc_id, organization_id=user.organization_id, filename=filename, document_type=document_type, version=0)
        db.add(document)
    document.version += 1
    document.status = DocumentStatus.processing
    document.processing_started_at = now
    document.vehicle_id = vehicle_id
    document.content_sha256 = hashlib.sha256(data).hexdigest()
    document.size_bytes = len(data)
    document.error_message = None
    document.uploaded_by = user.id
    db.commit()
    db.refresh(document)

    # Blocking pre-purge (spec §1.2.3): every earlier version's vectors go
    # before any new one is written. If Pinecone is unreachable we can't
    # guarantee that, so the upload fails rather than risk stale pollution.
    try:
        store.delete(org_filter(user.organization_id, {"document_id": {"$eq": str(doc_id)}}), settings.documents_namespace)
    except VectorSecurityViolation:
        raise
    except Exception as exc:  # noqa: BLE001
        document.status = DocumentStatus.failed
        document.error_message = f"pre-purge failed: {type(exc).__name__}"
        db.commit()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Vector store unavailable; upload not accepted")

    _executor.submit(_ingest, document.id, document.organization_id, document.version, kind, data)
    return document


def _ingest(document_id: uuid.UUID, organization_id: uuid.UUID, version: int, kind: str, data: bytes) -> None:
    settings = get_settings()
    db = _new_session()
    try:
        inference = get_rag_inference()
        units = extract_pdf_units(data) if kind == "pdf" else extract_text_units(data.decode("utf-8", errors="replace"))
        if not units:
            raise ValueError("no extractable text (scanned/image-only PDFs are not supported)")

        tables = [(i, u.markdown, u.context) for i, u in enumerate(units) if u.kind == "table"]
        complete = (
            (lambda prompt: groq_completion(settings.groq_api_key, settings.rag_summary_model, prompt))
            if settings.groq_api_key
            else None
        )
        summaries = summarize_tables(tables, complete, max_tables=settings.rag_max_summarized_tables)
        for failure in summaries.failures:
            db.add(DocumentIngestFailure(organization_id=organization_id, document_id=document_id, stage="table_summary",
                                         error_message=failure["error"], payload=failure))

        chunks = build_chunks(units, summaries.texts, chunk_size=settings.rag_chunk_size, chunk_overlap=settings.rag_chunk_overlap)
        if not chunks:
            raise ValueError("document produced no chunks")
        embed_inputs = [c.embed_text for c in chunks]
        dense = inference.embed_dense(embed_inputs, "passage")
        sparse = inference.embed_sparse(embed_inputs, "passage")

        document = db.get(Document, document_id)
        metadata_base = {"organization_id": str(organization_id), "document_id": str(document_id),
                         "document_type": document.document_type.value, "version": version}
        if document.vehicle_id is not None:
            metadata_base["vehicle_id"] = str(document.vehicle_id)
        vectors = [
            {"id": _vector_id(organization_id, document_id, version, i), "values": dense[i], "sparse_values": sparse[i],
             "metadata": {**metadata_base, "chunk_index": i}}
            for i in range(len(chunks))
        ]
        runner = _document_runner()
        failed_batches = 0
        for start in range(0, len(vectors), UPSERT_BATCH):
            job = {"op": "upsert", "store": "documents", "namespace": settings.documents_namespace,
                   "vectors": vectors[start : start + UPSERT_BATCH]}
            if not runner.run_sync(organization_id, job):
                failed_batches += 1  # already dead-lettered by the runner, replayable

        # Finalize under the row lock, and only if no newer upload superseded us.
        document = db.execute(select(Document).where(Document.id == document_id).with_for_update()).scalar_one()
        if document.version != version:
            db.rollback()
            logger.info("document %s v%d superseded by v%d; discarding", document_id, version, document.version)
            return
        db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()
        db.add_all(
            DocumentChunk(organization_id=organization_id, document_id=document_id, chunk_index=i, text=c.text)
            for i, c in enumerate(chunks)
        )
        document.chunk_count = len(chunks)
        document.tables_found = len(tables)
        document.tables_summarized = summaries.summarized
        document.processing_started_at = None
        if failed_batches:
            document.status = DocumentStatus.failed
            document.error_message = f"{failed_batches} vector batch(es) dead-lettered; replay from /memory/vector-jobs/failed"
        else:
            document.status = DocumentStatus.ready
        db.commit()
        search_cache.invalidate_org(organization_id)
    except Exception as exc:  # noqa: BLE001 -- a background failure must land on the document, not vanish
        db.rollback()
        logger.exception("ingestion failed for document %s v%d", document_id, version)
        document = db.execute(select(Document).where(Document.id == document_id).with_for_update()).scalar_one_or_none()
        if document is not None and document.version == version:
            document.status = DocumentStatus.failed
            document.processing_started_at = None
            document.error_message = f"{type(exc).__name__}: {exc}"[:1_000]
            db.add(DocumentIngestFailure(organization_id=organization_id, document_id=document_id, stage="ingest",
                                         error_message=document.error_message, payload={"version": version}))
            db.commit()
    finally:
        db.close()


# --- retrieval (spec §3) ------------------------------------------------------------


def search(
    db: Session,
    user: User,
    query: str,
    document_types: list[DocumentType] | None = None,
    document_ids: list[uuid.UUID] | None = None,
) -> tuple[list[dict], bool]:
    """Returns (results, served_from_cache). An empty list is the spec's
    "null payload": nothing cleared the relevance threshold.

    document_ids restricts the search to exactly those documents (the chat's "@" mentions): the vector query is
    filtered to them and every hit is re-checked against them in Postgres, so a mention can only narrow what the
    caller may see.

    If embedding, Pinecone or the reranker fails mid-search, this is a 503 --
    never unreranked results: skipping precision scoring would hand the LLM
    exactly the low-relevance context the threshold exists to keep out."""
    # A search is a read, so a transient failure (a dropped connection, a DNS lookup that fails once: seen on
    # developer machines as getaddrinfo 11002 to Pinecone) is retried a couple of times before it becomes a 503.
    for attempt in range(SEARCH_ATTEMPTS):
        try:
            return _search(db, user, query, document_types, document_ids)
        except (HTTPException, VectorSecurityViolation):
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("document search failed (attempt %d/%d): %s", attempt + 1, SEARCH_ATTEMPTS, type(exc).__name__, exc_info=attempt + 1 == SEARCH_ATTEMPTS)
            if attempt + 1 == SEARCH_ATTEMPTS:
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Document search temporarily unavailable")
            time.sleep(SEARCH_RETRY_DELAY_SECONDS * (attempt + 1))


def _search(
    db: Session, user: User, query: str, document_types: list[DocumentType] | None, document_ids: list[uuid.UUID] | None = None
) -> tuple[list[dict], bool]:
    settings = get_settings()
    permitted = allowed_types(user)
    scope = permitted & set(document_types) if document_types else permitted
    if not scope:
        return [], False
    store, inference = get_document_store(), get_rag_inference()
    if store is None or inference is None:
        raise _unavailable()

    dense_query = inference.embed_dense([query], "query")[0]
    only = sorted({str(i) for i in document_ids}) if document_ids else []
    cache_key = (str(user.organization_id), tuple(sorted(t.value for t in scope)), tuple(only))
    cached = search_cache.get(cache_key, dense_query)
    if cached is not None:
        return cached, True

    # Stage 2: convex hybrid search.
    sparse_query = inference.embed_sparse([query], "query")[0]
    dense_scaled, sparse_scaled = hybrid_scale(dense_query, sparse_query, settings.rag_alpha)
    clauses: list[dict] = [{"document_type": {"$in": sorted(t.value for t in scope)}}]
    if only:
        clauses.append({"document_id": {"$in": only}})
    filters = org_filter(user.organization_id, *clauses)
    matches = store.query(dense_scaled, settings.rag_candidate_k, filters, settings.documents_namespace, sparse_vector=sparse_scaled)

    # Re-check every hit against Postgres: org, allowed type, ready, current version.
    wanted: dict[uuid.UUID, set[tuple[int, int]]] = {}
    for match in matches:
        meta = match["metadata"]
        try:
            hit_document = uuid.UUID(meta["document_id"])
            if document_ids and hit_document not in set(document_ids):
                continue  # the vector filter already guarantees this; Postgres is the authority
            wanted.setdefault(hit_document, set()).add((int(meta["version"]), int(meta["chunk_index"])))
        except (KeyError, ValueError):
            continue
    if not wanted:
        return [], False
    documents = {
        d.id: d
        for d in db.execute(
            select(Document).where(
                Document.id.in_(wanted),
                Document.organization_id == user.organization_id,
                Document.status == DocumentStatus.ready,
                Document.document_type.in_(scope),
            )
        ).scalars()
    }
    current = {(doc_id, idx) for doc_id, hits in wanted.items() if doc_id in documents
               for version, idx in hits if version == documents[doc_id].version}
    chunks = list(
        db.execute(
            select(DocumentChunk).where(tuple_(DocumentChunk.document_id, DocumentChunk.chunk_index).in_(sorted(current)))
        ).scalars()
    ) if current else []

    # Stage 3: cross-encoder precision scoring.
    scored = inference.rerank(query, [c.text for c in chunks])
    ranked = sorted(((score, chunks[i]) for i, score in scored), key=lambda pair: pair[0], reverse=True)
    kept = [pair for pair in ranked if pair[0] >= settings.rag_rerank_threshold][: settings.rag_max_chunks]
    if not kept and ranked:
        top = ranked[0][0]
        runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
        if top >= settings.rag_rerank_floor and top >= settings.rag_rerank_dominance * max(runner_up, 0.001):
            kept = [ranked[0]]  # below the bar, but clearly the one passage that answers it
    results = [
        {
            "document_id": str(chunk.document_id),
            "filename": documents[chunk.document_id].filename,
            "document_type": documents[chunk.document_id].document_type.value,
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "relevance": round(score, 4),
        }
        for score, chunk in kept
    ]
    # Never cache an empty result: right after an upload Pinecone may not have
    # the new vectors yet, and a cached "nothing found" would hide the new
    # document for the whole TTL.
    if results:
        search_cache.put(cache_key, dense_query, results)
    return results, False


# --- management -------------------------------------------------------------------


def list_documents(db: Session, user: User) -> list[Document]:
    return list(
        db.execute(
            select(Document)
            .where(Document.organization_id == user.organization_id, Document.document_type.in_(allowed_types(user)))
            .order_by(Document.created_at.desc())
        ).scalars()
    )


def list_chunks(db: Session, user: User, document_id: uuid.UUID) -> list[DocumentChunk]:
    """The stored passages of a document the caller may see, in reading order. Empty while it is not ready: the
    chunks of an earlier version are replaced at the very end of ingestion, so a half-processed document shows none."""
    document = get_document(db, user, document_id)
    if document.status != DocumentStatus.ready:
        return []
    return list(
        db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document.id, DocumentChunk.organization_id == user.organization_id)
            .order_by(DocumentChunk.chunk_index)
        ).scalars()
    )


def get_document(db: Session, user: User, document_id: uuid.UUID) -> Document:
    document = db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.organization_id == user.organization_id,
            Document.document_type.in_(allowed_types(user)),
        )
    ).scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


def delete_document(db: Session, user: User, document_id: uuid.UUID) -> None:
    document = get_document(db, user, document_id)
    store = get_document_store()
    if store is None:
        raise _unavailable()
    try:
        store.delete(org_filter(user.organization_id, {"document_id": {"$eq": str(document_id)}}), get_settings().documents_namespace)
    except VectorSecurityViolation:
        raise
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Vector store unavailable; document not deleted")
    db.delete(document)
    db.commit()
    search_cache.invalidate_org(user.organization_id)
