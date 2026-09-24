"""Agent memory persistence -- short-term sessions/messages and the long-term
semantic vault. The embedding model runs in ai_agents/; this service only
stores vectors and compares them (pgvector cosine distance)."""

import re
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models.driver import Driver
from app.models.enums import MemoryEntityType, MemoryScope, UserRole
from app.models.memory import AgentMessage, AgentSession, SemanticMemory
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.memory import (
    AgentMessageCreate,
    AgentSessionSummaryUpdate,
    SemanticMemoryCreate,
    SemanticMemorySearchRequest,
    SemanticMemorySupersedeRequest,
)

# Spec: "When a 6th message is saved, an event is pushed" -- i.e. more than
# this many unsummarized messages means the window needs compressing.
SUMMARIZATION_TRIGGER = 5

DEDUPE_SIMILARITY_THRESHOLD = 0.98

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


def append_message(db: Session, user: User, session_id: uuid.UUID, data: AgentMessageCreate) -> tuple[AgentMessage, int]:
    session = _get_own_session(db, user, session_id)
    message = AgentMessage(session_id=session.id, role=data.role, content=data.content)
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
        embedding=data.embedding,
        created_by=user.id,
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


def _visible_to(user: User):
    """The RBAC scope boundary, applied to every read: same org, active, and
    personal facts only for their owner."""
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

    if data.embedding is not None:
        distance = SemanticMemory.embedding.cosine_distance(data.embedding)
        rows = db.execute(
            select(SemanticMemory, distance.label("distance"))
            .where(*conditions, SemanticMemory.embedding.is_not(None), distance <= data.max_distance)
            .order_by(distance)
            .limit(data.top_k)
        ).all()
        return [(row[0], float(row[1])) for row in rows]

    # No embedding: keyword fallback. _KEYWORD_RE admits only [A-Za-z0-9-],
    # so no LIKE wildcard can reach the pattern.
    if data.query_text:
        words = _keywords(data.query_text)
        if words:
            conditions.append(or_(*[SemanticMemory.content.ilike(f"%{w}%") for w in words]))
    rows = db.execute(
        select(SemanticMemory).where(*conditions).order_by(SemanticMemory.created_at.desc()).limit(data.top_k)
    ).scalars().all()
    return [(memory, None) for memory in rows]


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
    return memory


def supersede_entity_memories(
    db: Session, user: User, data: SemanticMemorySupersedeRequest
) -> tuple[SemanticMemory, list[uuid.UUID]]:
    """Without an embedding nothing is deactivated -- judging "same topic" by
    keywords alone would retire unrelated facts that merely mention the same
    vehicle, which is worse than keeping a stale one active."""
    _require_scope_write(user, MemoryScope.entity)
    _require_entity_in_org(db, user.organization_id, data.entity_type, data.entity_id)

    now = datetime.now(timezone.utc)
    deactivated: list[uuid.UUID] = []
    if data.embedding is not None:
        distance = SemanticMemory.embedding.cosine_distance(data.embedding)
        stale = (
            db.execute(
                select(SemanticMemory)
                .where(
                    SemanticMemory.organization_id == user.organization_id,
                    SemanticMemory.scope == MemoryScope.entity,
                    SemanticMemory.entity_id == data.entity_id,
                    SemanticMemory.is_active.is_(True),
                    SemanticMemory.embedding.is_not(None),
                    distance <= 1 - data.similarity_threshold,
                )
                .with_for_update()
            )
            .scalars()
            .all()
        )
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
        embedding=data.embedding,
        created_by=user.id,
    )
    db.add(created)
    db.commit()
    db.refresh(created)
    return created, deactivated


def dedupe_memories(db: Session, user: User, similarity_threshold: float = DEDUPE_SIMILARITY_THRESHOLD) -> list[uuid.UUID]:
    """Retention policy: within one org, among active facts sharing the same
    scope/owner/entity, any fact within `similarity_threshold` of an OLDER fact
    is a duplicate and is deactivated (soft-deleted, never hard-deleted) -- the
    oldest copy is the one kept."""
    older = aliased(SemanticMemory)
    newer = aliased(SemanticMemory)
    duplicate_ids = (
        db.execute(
            select(newer.id)
            .join(
                older,
                and_(
                    older.organization_id == newer.organization_id,
                    older.scope == newer.scope,
                    older.user_id.is_not_distinct_from(newer.user_id),
                    older.entity_id.is_not_distinct_from(newer.entity_id),
                    older.is_active.is_(True),
                    older.embedding.is_not(None),
                    or_(
                        older.created_at < newer.created_at,
                        and_(older.created_at == newer.created_at, older.id < newer.id),
                    ),
                    older.embedding.cosine_distance(newer.embedding) <= 1 - similarity_threshold,
                ),
            )
            .where(
                newer.organization_id == user.organization_id,
                newer.is_active.is_(True),
                newer.embedding.is_not(None),
            )
            .distinct()
        )
        .scalars()
        .all()
    )
    if not duplicate_ids:
        return []

    now = datetime.now(timezone.utc)
    for memory in db.execute(select(SemanticMemory).where(SemanticMemory.id.in_(duplicate_ids)).with_for_update()).scalars():
        memory.is_active = False
        memory.deactivated_at = now
    db.commit()
    return list(duplicate_ids)
