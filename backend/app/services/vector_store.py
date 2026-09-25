"""Vector storage for agent memory (Pinecone_Migration_Hardened.md §1, §4).

Tenant isolation for vectors rests on application code (Pinecone has no
foreign keys or row-level security), so it is enforced in two layers here:

1. build_rbac_filter() is the ONLY way memory_service builds a vector filter.
   It always pins organization_id and scope visibility, and ANDs any extra
   clauses so they can never widen or override them.
2. OrgScopeGuard is a runtime enforcer every store call passes through: a
   filter without a top-level organization_id pin, or an id outside the
   caller's org prefix, is refused before any request leaves the process and
   logged at CRITICAL.

Vector ids are "<organization_id>#<memory_id>" so id-based calls (fetch) can
be checked against the org too. Metadata carries only filter fields -- never
the memory text, which stays in Postgres.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from app.models.enums import MemoryScope
from app.models.user import User

logger = logging.getLogger("fleet.security")


class VectorSecurityViolation(Exception):
    pass


def vector_id(organization_id: Any, memory_id: Any) -> str:
    return f"{organization_id}#{memory_id}"


def memory_id_from_vector_id(value: str) -> str:
    return value.split("#", 1)[1]


def build_rbac_filter(user: User, *extra_clauses: dict[str, Any]) -> dict[str, Any]:
    """Centralized filter factory -- guarantees an organization_id pin and the
    scope visibility rule on every vector query.

    Corrects the spec's sketch in two places: (a) personal memories are visible
    ONLY to their owner, for every role -- the sketch let admins/fleet_managers
    read everyone's personal facts, a regression from agent-memory.md; (b) the
    sketch hid organization-scope facts from non-managers, contradicting the
    vault's own read rules. Extra clauses are ANDed (the sketch's dict.update()
    would let an extra "organization_id" or "$or" key silently replace the
    security clauses)."""
    if user is None or not user.organization_id:
        logger.critical("Vector filter requested without an organization context")
        raise VectorSecurityViolation("missing organization_id")

    visibility = {
        "$or": [
            {"$and": [{"scope": {"$eq": MemoryScope.personal.value}}, {"user_id": {"$eq": str(user.id)}}]},
            {"scope": {"$in": [MemoryScope.organization.value, MemoryScope.entity.value]}},
        ]
    }
    return {"$and": [{"organization_id": {"$eq": str(user.organization_id)}}, visibility, *extra_clauses]}


def org_filter(organization_id: Any, *extra_clauses: dict[str, Any]) -> dict[str, Any]:
    """For org-wide maintenance jobs (dedupe/prune/soft-delete by id), where no
    per-user visibility applies but the org pin still must."""
    return {"$and": [{"organization_id": {"$eq": str(organization_id)}}, *extra_clauses]}


def _pinned_org(filters: dict[str, Any] | None) -> str | None:
    """The organization_id a filter is pinned to, if pinned at the top level
    (directly, or as a direct member of a top-level $and). A pin nested under
    $or does NOT count -- an OR branch can be bypassed by its sibling."""
    if not isinstance(filters, dict):
        return None

    def _value(clause: Any) -> str | None:
        if isinstance(clause, dict) and "organization_id" in clause:
            value = clause["organization_id"]
            if isinstance(value, dict):
                value = value.get("$eq") if set(value) == {"$eq"} else None
            return value if isinstance(value, str) and value else None
        return None

    pinned = _value(filters)
    if pinned is None:
        for clause in filters.get("$and") or []:
            pinned = pinned or _value(clause)
    return pinned


class VectorStore(Protocol):
    """Vendor-neutral surface. Swapping Pinecone for Qdrant/Milvus/pgvector
    means writing another class with these methods -- memory_service never
    imports a vendor SDK."""

    def query(
        self, vector: list[float], top_k: int, filters: dict[str, Any], namespace: str, *, sparse_vector: dict | None = None
    ) -> list[dict[str, Any]]: ...
    def upsert(self, vectors: list[dict[str, Any]], namespace: str) -> None: ...
    def update_metadata(self, filters: dict[str, Any], set_metadata: dict[str, Any], namespace: str) -> None: ...
    def delete(self, filters: dict[str, Any], namespace: str) -> None: ...
    def fetch(self, ids: list[str], organization_id: str, namespace: str) -> dict[str, list[float]]: ...


class OrgScopeGuard:
    """Runtime enforcer wrapped around any VectorStore."""

    def __init__(self, inner: VectorStore) -> None:
        self.inner = inner

    @staticmethod
    def _refuse(operation: str, detail: str) -> None:
        logger.critical("SECURITY: refused vector %s -- %s", operation, detail)
        raise VectorSecurityViolation(f"{operation}: {detail}")

    def _require_pinned(self, operation: str, filters: dict[str, Any]) -> str:
        pinned = _pinned_org(filters)
        if pinned is None:
            self._refuse(operation, "filter is not pinned to an organization_id")
        return pinned

    def query(self, vector, top_k, filters, namespace, *, sparse_vector=None):
        self._require_pinned("query", filters)
        if sparse_vector is None:
            return self.inner.query(vector, top_k, filters, namespace)
        return self.inner.query(vector, top_k, filters, namespace, sparse_vector=sparse_vector)

    def upsert(self, vectors, namespace):
        for item in vectors:
            org = (item.get("metadata") or {}).get("organization_id")
            if not org or not str(item.get("id", "")).startswith(f"{org}#"):
                self._refuse("upsert", f"vector {item.get('id')!r} lacks a matching organization_id")
        return self.inner.upsert(vectors, namespace)

    def update_metadata(self, filters, set_metadata, namespace):
        self._require_pinned("update", filters)
        if "organization_id" in set_metadata:
            self._refuse("update", "organization_id cannot be rewritten")
        return self.inner.update_metadata(filters, set_metadata, namespace)

    def delete(self, filters, namespace):
        self._require_pinned("delete", filters)
        return self.inner.delete(filters, namespace)

    def fetch(self, ids, organization_id, namespace):
        if not organization_id:
            self._refuse("fetch", "no organization_id")
        foreign = [i for i in ids if not i.startswith(f"{organization_id}#")]
        if foreign:
            self._refuse("fetch", f"{len(foreign)} id(s) outside organization {organization_id}")
        return self.inner.fetch(ids, organization_id, namespace)


def _is_missing_namespace(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) == 404 and "namespace not found" in str(exc).lower()


class PineconeVectorStore:
    """Verified live against serverless: query/fetch on a namespace that has
    never been written return empty, but update-by-filter and delete-by-filter
    raise 404 "Namespace not found". Nothing to update is success here --
    otherwise the first prune on a fresh index would retry and dead-letter."""

    def __init__(self, index: Any) -> None:
        self.index = index

    def query(self, vector, top_k, filters, namespace, *, sparse_vector=None):
        # sparse_vector (hybrid search) requires a dotproduct index.
        response = self.index.query(
            vector=vector, top_k=top_k, filter=filters, namespace=namespace, include_metadata=True,
            **({"sparse_vector": sparse_vector} if sparse_vector is not None else {}),
        )
        return [{"id": m.id, "score": float(m.score), "metadata": dict(m.metadata or {})} for m in response.matches]

    def upsert(self, vectors, namespace):
        self.index.upsert(vectors=vectors, namespace=namespace, show_progress=False)

    def update_metadata(self, filters, set_metadata, namespace):
        try:
            self.index.update(filter=filters, set_metadata=set_metadata, namespace=namespace)
        except Exception as exc:
            if not _is_missing_namespace(exc):
                raise

    def delete(self, filters, namespace):
        try:
            self.index.delete(filter=filters, namespace=namespace)
        except Exception as exc:
            if not _is_missing_namespace(exc):
                raise

    def fetch(self, ids, organization_id, namespace):
        found: dict[str, list[float]] = {}
        for start in range(0, len(ids), 100):  # Pinecone fetch accepts at most 100 ids per call
            response = self.index.fetch(ids=ids[start : start + 100], namespace=namespace)
            found.update({vid: list(vec.values) for vid, vec in response.vectors.items()})
        return found


_stores: dict[str, VectorStore | None] = {}


def _build_guarded_store(index_name: str) -> VectorStore | None:
    """If Pinecone can't be reached while building (describe_index needs the
    network), return None for this call and retry on the next one -- a
    request must never 500 because Pinecone is unreachable."""
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.pinecone_api_key:
        _stores[index_name] = None
        return None
    try:
        from pinecone import Pinecone

        client = Pinecone(api_key=settings.pinecone_api_key)
        index = client.Index(host=client.describe_index(index_name).host)
    except Exception:  # noqa: BLE001
        logger.warning("Pinecone index %r unreachable while initializing; degrading for now", index_name, exc_info=True)
        return None
    _stores[index_name] = OrgScopeGuard(PineconeVectorStore(index))
    return _stores[index_name]


def get_vector_store() -> VectorStore | None:
    """The guarded agent-memory store (cosine index), or None when
    PINECONE_API_KEY is unset (memory then runs Postgres-only)."""
    from app.core.config import get_settings

    name = get_settings().pinecone_index
    return _stores[name] if name in _stores else _build_guarded_store(name)


def get_document_store() -> VectorStore | None:
    """The guarded document-RAG store (dotproduct index, for hybrid search)."""
    from app.core.config import get_settings

    name = get_settings().pinecone_documents_index
    return _stores[name] if name in _stores else _build_guarded_store(name)


def _set(index_name: str, store: VectorStore | None) -> None:
    """Test/ops hook. Any store set here is wrapped in the guard -- tests
    exercise the same enforcement production does."""
    _stores[index_name] = OrgScopeGuard(store) if store is not None and not isinstance(store, OrgScopeGuard) else store


def set_vector_store(store: VectorStore | None) -> None:
    from app.core.config import get_settings

    _set(get_settings().pinecone_index, store)


def set_document_store(store: VectorStore | None) -> None:
    from app.core.config import get_settings

    _set(get_settings().pinecone_documents_index, store)


def get_namespace() -> str:
    from app.core.config import get_settings

    return get_settings().pinecone_namespace
