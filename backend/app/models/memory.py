import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import AgentMessageRole, MemoryEntityType, MemoryScope
from app.models.mixins import OrgScopedMixin

# Embedding dimension shared by every supported model (nomic-embed-text-v1.5,
# Pinecone-hosted llama-text-embed-v2 at 768). Vectors are computed by
# ai_agents/ and stored in Pinecone -- never in Postgres.
EMBEDDING_DIM = 768


class AgentSession(Base, OrgScopedMixin):
    """Short-term memory for one Grand Orchestrator conversation. Always owned
    by exactly one user -- never shared across users, even within an org."""

    __tablename__ = "agent_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    running_summary: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # Bumped on every summary write; a summarizer must present the version it
    # read, so two workers summarizing from the same stale summary can't both win.
    summary_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (Index("ix_agent_messages_session_unsummarized", "session_id", "is_summarized", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[AgentMessageRole] = mapped_column(SAEnum(AgentMessageRole, name="agent_message_role"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_summarized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )


class SemanticMemory(Base, OrgScopedMixin):
    """Long-term vault -- the system of record. `scope` decides who may see a
    fact: personal -> only user_id; organization -> everyone in the org;
    entity -> everyone in the org, attached to one vehicle/driver. The check
    constraints make an ill-scoped row unrepresentable.

    The vector itself lives in Pinecone (id "<organization_id>#<id>"), carrying
    only filter metadata -- never `content`. Every Pinecone hit is re-checked
    against this table before it is returned, so Postgres stays the authority
    on visibility and is_active even while Pinecone is eventually consistent."""

    __tablename__ = "semantic_memories"
    __table_args__ = (
        CheckConstraint("scope != 'personal' OR user_id IS NOT NULL", name="ck_semantic_memories_personal_has_user"),
        CheckConstraint(
            "scope != 'entity' OR (entity_id IS NOT NULL AND entity_type IS NOT NULL)",
            name="ck_semantic_memories_entity_has_entity",
        ),
        Index("ix_semantic_memories_scope_lookup", "organization_id", "scope", "is_active"),
        Index("ix_semantic_memories_entity", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope: Mapped[MemoryScope] = mapped_column(SAEnum(MemoryScope, name="memory_scope"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    # No FK: points at either vehicles.id or drivers.id depending on entity_type.
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    entity_type: Mapped[MemoryEntityType | None] = mapped_column(
        SAEnum(MemoryEntityType, name="memory_entity_type"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # True once a vector was sent to Pinecone for this row. False when
    # ai_agents had no embedding provider: still recalled by scope/keyword.
    has_vector: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    # clock_timestamp, not now(): dedupe keeps the NEWEST copy, which needs
    # distinct timestamps even for rows inserted in one transaction.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FailedVectorJob(Base, OrgScopedMixin):
    """Dead-letter queue: a Pinecone write that failed all retries. `payload`
    is the complete, replayable job (op + filters/vectors + namespace), so an
    admin can retry it verbatim once Pinecone is reachable again."""

    __tablename__ = "failed_vector_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
