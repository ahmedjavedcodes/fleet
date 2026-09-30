"""Agent memory persistence -- short-term sessions/messages and the long-term
semantic vault.

Postgres is the system of record for every memory (content, scope, owner,
is_active). Vectors live in Pinecone behind app.services.vector_store, which
enforces the org pin on every call; writes to it go through the retrying,
dead-lettering VectorJobRunner so the request never waits on Pinecone. Every
vector hit is re-checked against Postgres before it is returned, so
eventual consistency in Pinecone can never surface a deactivated or
invisible memory. The embedding model runs in ai_agents/.
"""

import logging
import math
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.driver import Driver
from app.models.enums import AgentMessageRole, MemoryEntityType, MemoryScope, UserRole
from app.models.memory import AgentMessage, AgentSession, FailedVectorJob, SemanticMemory
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.memory import (
    AgentSessionListItem,
    AgentMessageCreate,
    AgentSessionSummaryUpdate,
    SemanticMemoryCreate,
    SemanticMemorySearchRequest,
    SemanticMemorySupersedeRequest,
)
from app.services.vector_jobs import execute_job, get_vector_runner
from app.services.vector_store import (
    VectorSecurityViolation,
    build_rbac_filter,
    get_document_store,
    get_namespace,
    get_vector_store,
    memory_id_from_vector_id,
    org_filter,
    vector_id,
)

logger = logging.getLogger("fleet.memory")

# Spec: "When a 6th message is saved, an event is pushed" -- i.e. more than
# this many unsummarized messages means the window needs compressing.
SUMMARIZATION_TRIGGER = 5

DEDUPE_SIMILARITY_THRESHOLD = 0.98
PRUNE_AFTER_DAYS = 90

# personal: anyone, for themselves. organization-wide facts shape every
# user's answers, so only managers may write them. entity facts additionally
# allow mechanics, who are the source of most vehicle-condition knowledge.
_SCOPE_WRITE_ROLES: dict[MemoryScope, frozenset[UserRole]] = {
    MemoryScope.personal: frozenset(UserRole),
    MemoryScope.organization: frozenset({UserRole.admin, UserRole.fleet_manager}),
    MemoryScope.entity: frozenset({UserRole.admin, UserRole.fleet_manager, UserRole.mechanic}),
}

_SESSION_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
_MEMORY_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")


# --- Short-term memory -----------------------------------------------------------


def create_session(db: Session, user: User) -> AgentSession:
    session = AgentSession(organization_id=user.organization_id, user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _get_own_session(db: Session, user: User, session_id: uuid.UUID, *, for_update: bool = False) -> AgentSession:
    """Sessions are private to their owner -- another user in the same org
    gets a 404, not a 403, so session ids can't be probed for existence."""
    stmt = select(AgentSession).where(
        AgentSession.id == session_id,
        AgentSession.organization_id == user.organization_id,
        AgentSession.user_id == user.id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    session = db.execute(stmt).scalar_one_or_none()
    if session is None:
        raise _SESSION_NOT_FOUND
    return session


def get_session(db: Session, user: User, session_id: uuid.UUID) -> AgentSession:
    return _get_own_session(db, user, session_id)


def _unsummarized_stmt(session_id: uuid.UUID):
    return select(AgentMessage).where(AgentMessage.session_id == session_id, AgentMessage.is_summarized.is_(False))


TITLE_MAX_LENGTH = 60
UNTITLED = "New chat"


def derive_title(text: str) -> str:
    """A short sidebar title from the first thing the user said: whitespace collapsed,
    cut at a word boundary. Deliberately not an LLM call -- it must be instant, free,
    and unable to fail a chat turn."""
    flat = " ".join(text.split())
    if not flat:
        return UNTITLED
    if len(flat) <= TITLE_MAX_LENGTH:
        return flat
    cut = flat[: TITLE_MAX_LENGTH - 1].rsplit(" ", 1)[0] or flat[: TITLE_MAX_LENGTH - 1]
    return cut.rstrip(" ,.;:-") + "…"


def list_sessions(db: Session, user: User, limit: int = 100) -> list[AgentSessionListItem]:
    """The caller's own conversations, most recently active first. Empty sessions (created
    but never used, e.g. by opening a new chat) are left out."""
    first_user_message = (
        select(AgentMessage.content)
        .where(AgentMessage.session_id == AgentSession.id, AgentMessage.role == AgentMessageRole.user)
        .order_by(AgentMessage.created_at)
        .limit(1)
        .scalar_subquery()
    )
    message_count = (
        select(func.count(AgentMessage.id)).where(AgentMessage.session_id == AgentSession.id).scalar_subquery()
    )
    rows = db.execute(
        select(AgentSession, message_count, first_user_message)
        .where(AgentSession.organization_id == user.organization_id, AgentSession.user_id == user.id)
        .where(message_count > 0)
        .order_by(AgentSession.updated_at.desc(), AgentSession.id)
        .limit(limit)
    ).all()
    return [
        AgentSessionListItem(
            id=s.id,
            title=s.title or (derive_title(first) if first else UNTITLED),
            message_count=count,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s, count, first in rows
    ]


def rename_session(db: Session, user: User, session_id: uuid.UUID, title: str) -> AgentSession:
    session = _get_own_session(db, user, session_id)
    session.title = title
    # Renaming isn't activity. Marking updated_at as written (with its unchanged value) keeps the
    # onupdate hook from bumping it, so the conversation keeps its place in the list.
    flag_modified(session, "updated_at")
    db.commit()
    db.refresh(session)
    return session


def delete_session(db: Session, user: User, session_id: uuid.UUID) -> None:
    """Permanently deletes one of the caller's own conversations and its whole
    transcript. The messages are deleted explicitly rather than trusting the
    FK's ON DELETE CASCADE alone, so this holds even on a database where the
    constraint predates the cascade. Locked FOR UPDATE so it can't interleave
    with a summary commit or a message append on the same session."""
    session = _get_own_session(db, user, session_id, for_update=True)
    db.execute(delete(AgentMessage).where(AgentMessage.session_id == session.id))
    db.delete(session)
    db.commit()


def list_messages(db: Session, user: User, session_id: uuid.UUID) -> tuple[AgentSession, list[AgentMessage]]:
    """The full transcript, including messages already folded into the running summary."""
    session = _get_own_session(db, user, session_id)
    messages = db.execute(
        select(AgentMessage).where(AgentMessage.session_id == session.id).order_by(AgentMessage.created_at)
    ).scalars().all()
    return session, list(messages)


def append_message(db: Session, user: User, session_id: uuid.UUID, data: AgentMessageCreate) -> tuple[AgentMessage, int]:
    session = _get_own_session(db, user, session_id)
    message = AgentMessage(session_id=session.id, role=data.role, content=data.content)
    if session.title is None and data.role == AgentMessageRole.user:
        session.title = derive_title(data.content)
    db.add(message)
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(message)
    count = db.execute(select(func.count()).select_from(_unsummarized_stmt(session.id).subquery())).scalar_one()
    return message, count


def get_context(db: Session, user: User, session_id: uuid.UUID) -> tuple[AgentSession, list[AgentMessage]]:
    session = _get_own_session(db, user, session_id)
    messages = db.execute(_unsummarized_stmt(session.id).order_by(AgentMessage.created_at)).scalars().all()
    return session, list(messages)


def apply_summary(db: Session, user: User, session_id: uuid.UUID, data: AgentSessionSummaryUpdate) -> AgentSession:
    """The only write path for running_summary. Two layers of concurrency
    protection, both inside one transaction:

    1. The session row is locked FOR UPDATE and summary_version compared, so
       two summarizers that read the same summary can't both commit.
    2. The messages being folded in are locked FOR UPDATE SKIP LOCKED and must
       all still be unsummarized, so a message can never be counted twice.
    Either check failing is a 409 -- the losing worker drops its result.
    """
    session = _get_own_session(db, user, session_id, for_update=True)
    if session.summary_version != data.expected_summary_version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Summary was updated concurrently")

    wanted = set(data.message_ids)
    claimed = (
        db.execute(_unsummarized_stmt(session.id).where(AgentMessage.id.in_(wanted)).with_for_update(skip_locked=True))
        .scalars()
        .all()
    )
    if len(claimed) != len(wanted):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Some messages are already summarized or being summarized"
        )

    for message in claimed:
        message.is_summarized = True
    session.running_summary = data.running_summary
    session.summary_version += 1
    db.commit()
    db.refresh(session)
    return session


# --- Long-term vault ---------------------------------------------------------------


def _require_scope_write(user: User, scope: MemoryScope) -> None:
    if user.role not in _SCOPE_WRITE_ROLES[scope]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=f"Role '{user.role.value}' cannot write {scope.value} memories"
        )


def _require_entity_in_org(db: Session, org_id: uuid.UUID, entity_type: MemoryEntityType, entity_id: uuid.UUID) -> None:
    model = Vehicle if entity_type == MemoryEntityType.vehicle else Driver
    exists = db.execute(
        select(model.id).where(model.id == entity_id, model.organization_id == org_id, model.is_deleted.is_(False))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{entity_type.value.capitalize()} not found")


# --- vector bookkeeping (always background, always org-pinned) --------------------


def _epoch() -> int:
    return int(time.time())


def _vector_metadata(memory: SemanticMemory) -> dict:
    """Filter fields only -- the memory text never leaves Postgres. Pinecone
    metadata can't hold nulls, so absent owner/entity keys are omitted."""
    metadata = {
        "organization_id": str(memory.organization_id),
        "memory_id": str(memory.id),
        "scope": memory.scope.value,
        "is_active": True,
        "updated_at": _epoch(),
    }
    if memory.user_id is not None:
        metadata["user_id"] = str(memory.user_id)
    if memory.entity_id is not None:
        metadata["entity_id"] = str(memory.entity_id)
        metadata["entity_type"] = memory.entity_type.value
    return metadata


def _schedule_upsert(memory: SemanticMemory, embedding: list[float]) -> None:
    get_vector_runner().submit(
        memory.organization_id,
        {
            "op": "upsert",
            "namespace": get_namespace(),
            "vectors": [
                {"id": vector_id(memory.organization_id, memory.id), "values": embedding, "metadata": _vector_metadata(memory)}
            ],
        },
    )


def _memory_ids_clause(memory_ids: list[uuid.UUID]) -> dict:
    return {"memory_id": {"$in": [str(i) for i in memory_ids]}}


def _schedule_soft_delete(organization_id: uuid.UUID, memory_ids: list[uuid.UUID]) -> None:
    """Supersede/deactivate: metadata flips to is_active=False (spec §2), so
    fetch_memory's active filter excludes it; the monthly prune hard-deletes
    it 90 days later using updated_at."""
    if memory_ids:
        get_vector_runner().submit(
            organization_id,
            {
                "op": "update_metadata",
                "namespace": get_namespace(),
                "filters": org_filter(organization_id, _memory_ids_clause(memory_ids)),
                "set_metadata": {"is_active": False, "updated_at": _epoch()},
            },
        )


def _schedule_hard_delete(organization_id: uuid.UUID, memory_ids: list[uuid.UUID]) -> None:
    if memory_ids:
        get_vector_runner().submit(
            organization_id,
            {
                "op": "delete",
                "namespace": get_namespace(),
                "filters": org_filter(organization_id, _memory_ids_clause(memory_ids)),
            },
        )


# --- writes ------------------------------------------------------------------------


def create_memory(db: Session, user: User, data: SemanticMemoryCreate) -> SemanticMemory:
    _require_scope_write(user, data.scope)
    if data.scope == MemoryScope.entity:
        _require_entity_in_org(db, user.organization_id, data.entity_type, data.entity_id)

    memory = SemanticMemory(
        organization_id=user.organization_id,
        scope=data.scope,
        user_id=user.id if data.scope == MemoryScope.personal else None,
        entity_id=data.entity_id,
        entity_type=data.entity_type,
        content=data.content,
        has_vector=data.embedding is not None and get_vector_store() is not None,
        created_by=user.id,
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    if memory.has_vector:
        _schedule_upsert(memory, data.embedding)
    return memory


def deactivate_memory(db: Session, user: User, memory_id: uuid.UUID) -> SemanticMemory:
    memory = db.execute(
        select(SemanticMemory).where(SemanticMemory.id == memory_id, _visible_to(user)).with_for_update()
    ).scalar_one_or_none()
    if memory is None:
        raise _MEMORY_NOT_FOUND
    _require_scope_write(user, memory.scope)
    memory.is_active = False
    memory.deactivated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(memory)
    if memory.has_vector:
        _schedule_soft_delete(memory.organization_id, [memory.id])
    return memory


def supersede_entity_memories(
    db: Session, user: User, data: SemanticMemorySupersedeRequest
) -> tuple[SemanticMemory, list[uuid.UUID]]:
    """Staleness post-hook. Postgres flips is_active synchronously (so reads,
    which always re-check Postgres, are correct immediately); the Pinecone
    metadata update and the new vector follow in the background.

    Without an embedding -- or with Pinecone unreachable -- nothing is
    deactivated: judging "same topic" by keywords would retire unrelated facts
    that merely mention the same vehicle."""
    _require_scope_write(user, MemoryScope.entity)
    _require_entity_in_org(db, user.organization_id, data.entity_type, data.entity_id)

    store = get_vector_store()
    candidate_ids: list[uuid.UUID] = []
    if data.embedding is not None and store is not None:
        try:
            matches = store.query(
                data.embedding,
                50,
                org_filter(
                    user.organization_id,
                    {"scope": {"$eq": MemoryScope.entity.value}},
                    {"entity_id": {"$eq": str(data.entity_id)}},
                    {"is_active": {"$eq": True}},
                ),
                get_namespace(),
            )
            candidate_ids = [
                uuid.UUID(memory_id_from_vector_id(m["id"])) for m in matches if m["score"] >= data.similarity_threshold
            ]
        except VectorSecurityViolation:
            raise
        except Exception:  # noqa: BLE001 -- degrade to insert-only rather than fail the write
            logger.warning("supersede: vector query failed, storing without deactivation", exc_info=True)

    now = datetime.now(timezone.utc)
    deactivated: list[uuid.UUID] = []
    if candidate_ids:
        stale = db.execute(
            select(SemanticMemory)
            .where(
                SemanticMemory.id.in_(candidate_ids),
                SemanticMemory.organization_id == user.organization_id,
                SemanticMemory.scope == MemoryScope.entity,
                SemanticMemory.entity_id == data.entity_id,
                SemanticMemory.is_active.is_(True),
            )
            .with_for_update()
        ).scalars().all()
        for memory in stale:
            memory.is_active = False
            memory.deactivated_at = now
            deactivated.append(memory.id)

    created = SemanticMemory(
        organization_id=user.organization_id,
        scope=MemoryScope.entity,
        entity_id=data.entity_id,
        entity_type=data.entity_type,
        content=data.content,
        has_vector=data.embedding is not None and store is not None,
        created_by=user.id,
    )
    db.add(created)
    db.commit()
    db.refresh(created)
    _schedule_soft_delete(user.organization_id, deactivated)
    if created.has_vector:
        _schedule_upsert(created, data.embedding)
    return created, deactivated


# --- reads -------------------------------------------------------------------------


def _visible_to(user: User):
    """Postgres-side RBAC boundary -- the same rule build_rbac_filter encodes
    for Pinecone, applied again to every row actually returned."""
    return and_(
        SemanticMemory.organization_id == user.organization_id,
        SemanticMemory.is_active.is_(True),
        or_(SemanticMemory.scope != MemoryScope.personal, SemanticMemory.user_id == user.id),
    )


_KEYWORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]{3,}")


def _keywords(text: str, limit: int = 8) -> list[str]:
    seen: list[str] = []
    for word in _KEYWORD_RE.findall(text):
        lowered = word.lower()
        if lowered not in seen:
            seen.append(lowered)
        if len(seen) == limit:
            break
    return seen


def search_memories(db: Session, user: User, data: SemanticMemorySearchRequest) -> list[tuple[SemanticMemory, float | None]]:
    conditions = [_visible_to(user)]
    if data.entity_ids:
        conditions.append(or_(SemanticMemory.scope != MemoryScope.entity, SemanticMemory.entity_id.in_(data.entity_ids)))

    store = get_vector_store()
    if data.embedding is not None and store is not None:
        try:
            return _vector_search(db, user, data, store, conditions)
        except VectorSecurityViolation:
            raise
        except Exception:  # noqa: BLE001 -- Pinecone down: degrade to keyword recall, never a 500
            logger.warning("memory search: vector query failed, falling back to keywords", exc_info=True)

    # Keyword fallback. _KEYWORD_RE admits only [A-Za-z0-9-], so no LIKE
    # wildcard can reach the pattern.
    if data.query_text:
        words = _keywords(data.query_text)
        if words:
            conditions.append(or_(*[SemanticMemory.content.ilike(f"%{w}%") for w in words]))
    rows = db.execute(
        select(SemanticMemory).where(*conditions).order_by(SemanticMemory.created_at.desc()).limit(data.top_k)
    ).scalars().all()
    return [(memory, None) for memory in rows]


def _vector_search(db, user, data, store, conditions) -> list[tuple[SemanticMemory, float | None]]:
    clauses: list[dict] = [{"is_active": {"$eq": True}}]
    if data.entity_ids:
        clauses.append(
            {"$or": [{"scope": {"$ne": MemoryScope.entity.value}}, {"entity_id": {"$in": [str(i) for i in data.entity_ids]}}]}
        )
    # Over-fetch: some hits may be dropped by the Postgres re-check below
    # (e.g. deactivated moments ago, before Pinecone's metadata caught up).
    matches = store.query(data.embedding, min(data.top_k * 2, 40), build_rbac_filter(user, *clauses), get_namespace())
    distances: dict[uuid.UUID, float] = {}
    for match in matches:
        distance = 1.0 - match["score"]
        if distance <= data.max_distance:
            distances[uuid.UUID(memory_id_from_vector_id(match["id"]))] = distance
    if not distances:
        return []
    rows = db.execute(select(SemanticMemory).where(*conditions, SemanticMemory.id.in_(distances))).scalars().all()
    rows = sorted(rows, key=lambda memory: distances[memory.id])[: data.top_k]
    return [(memory, distances[memory.id]) for memory in rows]


# --- retention (Pinecone_Migration_Hardened.md §2) --------------------------------


def _cosine(a: list[float], b: list[float]) -> float:
    dot = math.fsum(x * y for x, y in zip(a, b))
    norm = math.sqrt(math.fsum(x * x for x in a)) * math.sqrt(math.fsum(y * y for y in b))
    return dot / norm if norm else 0.0


def dedupe_memories(
    db: Session, organization_id: uuid.UUID, similarity_threshold: float = DEDUPE_SIMILARITY_THRESHOLD
) -> list[uuid.UUID]:
    """Within one org, among active facts sharing scope/owner/entity, any fact
    at or above `similarity_threshold` to a NEWER fact is a duplicate: it is
    deactivated in Postgres and its vector deleted. The newest copy is kept
    (spec §2). No vector store = nothing to compare = no-op."""
    store = get_vector_store()
    if store is None:
        return []
    rows = db.execute(
        select(SemanticMemory)
        .where(
            SemanticMemory.organization_id == organization_id,
            SemanticMemory.is_active.is_(True),
            SemanticMemory.has_vector.is_(True),
        )
        .order_by(SemanticMemory.created_at.desc(), SemanticMemory.id.desc())
    ).scalars().all()
    if not rows:
        return []
    vectors = store.fetch([vector_id(organization_id, r.id) for r in rows], str(organization_id), get_namespace())

    kept: dict[tuple, list[list[float]]] = {}
    duplicates: list[SemanticMemory] = []
    for memory in rows:  # newest first
        vector = vectors.get(vector_id(organization_id, memory.id))
        if vector is None:
            continue  # vector not written yet (or dead-lettered) -- can't judge, leave it
        group = kept.setdefault((memory.scope, memory.user_id, memory.entity_id), [])
        if any(_cosine(vector, other) >= similarity_threshold for other in group):
            duplicates.append(memory)
        else:
            group.append(vector)

    if not duplicates:
        return []
    now = datetime.now(timezone.utc)
    ids = [m.id for m in duplicates]
    for memory in db.execute(select(SemanticMemory).where(SemanticMemory.id.in_(ids)).with_for_update()).scalars():
        memory.is_active = False
        memory.deactivated_at = now
    db.commit()
    _schedule_hard_delete(organization_id, ids)
    return ids


def prune_inactive_vectors(db: Session, organization_id: uuid.UUID, older_than_days: int = PRUNE_AFTER_DAYS) -> datetime | None:
    """Hard-purge vectors soft-deleted more than `older_than_days` ago (spec
    §2). The Postgres rows are kept as the audit trail -- only the vectors go.
    Returns the cutoff used, or None when no vector store is configured."""
    if get_vector_store() is None:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    get_vector_runner().submit(
        organization_id,
        {
            "op": "delete",
            "namespace": get_namespace(),
            "filters": org_filter(
                organization_id, {"is_active": {"$eq": False}}, {"updated_at": {"$lt": int(cutoff.timestamp())}}
            ),
        },
    )
    return cutoff


# --- dead-letter queue (Pinecone_Migration_Hardened.md §3) ------------------------


def list_failed_vector_jobs(db: Session, organization_id: uuid.UUID) -> list[FailedVectorJob]:
    return list(
        db.execute(
            select(FailedVectorJob)
            .where(FailedVectorJob.organization_id == organization_id)
            .order_by(FailedVectorJob.created_at)
        ).scalars()
    )


def retry_failed_vector_job(db: Session, organization_id: uuid.UUID, job_id: uuid.UUID) -> None:
    """Replays a dead-lettered job synchronously; removes it only on success."""
    job = db.execute(
        select(FailedVectorJob)
        .where(FailedVectorJob.id == job_id, FailedVectorJob.organization_id == organization_id)
        .with_for_update()
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Failed job not found")
    # Jobs are tagged with the index they belong to; replaying a document
    # upsert against the memory index would write into the wrong corpus.
    store = get_document_store() if job.payload.get("store") == "documents" else get_vector_store()
    if store is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Vector store is not configured")
    try:
        execute_job(store, job.payload)
    except VectorSecurityViolation:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Job payload failed the org-scope check")
    except Exception as exc:  # noqa: BLE001
        job.attempts += 1
        job.error_message = f"{type(exc).__name__}: {exc}"[:2_000]
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Retry failed: {job.error_message}")
    db.delete(job)
    db.commit()
