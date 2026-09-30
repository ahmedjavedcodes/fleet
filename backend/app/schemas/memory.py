import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import AgentMessageRole, MemoryEntityType, MemoryScope
from app.models.memory import EMBEDDING_DIM


def _check_embedding(value: list[float] | None) -> list[float] | None:
    if value is not None and len(value) != EMBEDDING_DIM:
        raise ValueError(f"embedding must have exactly {EMBEDDING_DIM} dimensions, got {len(value)}")
    return value


# --- Short-term memory -----------------------------------------------------------


class AgentSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None = None
    running_summary: str
    summary_version: int
    created_at: datetime
    updated_at: datetime


class AgentSessionListItem(BaseModel):
    """One row of the chat sidebar. Only sessions with at least one message are listed."""

    id: uuid.UUID
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class AgentSessionRename(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)


class AgentMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: AgentMessageRole
    content: str = Field(min_length=1, max_length=20_000)


class AgentMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: AgentMessageRole
    content: str
    is_summarized: bool
    created_at: datetime


class AgentMessageAppendResponse(BaseModel):
    message: AgentMessageResponse
    unsummarized_count: int
    needs_summarization: bool


class AgentSessionContextResponse(BaseModel):
    session: AgentSessionResponse
    unsummarized_messages: list[AgentMessageResponse]


class AgentSessionSummaryUpdate(BaseModel):
    """Written by ai_agents' background summarizer. expected_summary_version
    is the version it read before summarizing -- a mismatch means another
    worker already folded newer messages in, and this write is rejected (409)
    rather than silently overwriting that work."""

    model_config = ConfigDict(extra="forbid")

    message_ids: list[uuid.UUID] = Field(min_length=1)
    running_summary: str = Field(max_length=20_000)
    expected_summary_version: int = Field(ge=0)


# --- Long-term vault ---------------------------------------------------------------


class SemanticMemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: MemoryScope
    content: str = Field(min_length=1, max_length=2_000)
    entity_id: uuid.UUID | None = None
    entity_type: MemoryEntityType | None = None
    embedding: list[float] | None = None

    validate_embedding_dim = field_validator("embedding")(_check_embedding)

    @model_validator(mode="after")
    def _entity_fields_match_scope(self) -> "SemanticMemoryCreate":
        if self.scope == MemoryScope.entity:
            if self.entity_id is None or self.entity_type is None:
                raise ValueError("entity scope requires entity_id and entity_type")
        elif self.entity_id is not None or self.entity_type is not None:
            raise ValueError("entity_id/entity_type are only allowed with entity scope")
        return self


class SemanticMemoryResponse(BaseModel):
    """embedding is deliberately omitted -- 768 floats per row is useless to
    every caller and would dominate response size."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope: MemoryScope
    user_id: uuid.UUID | None
    entity_id: uuid.UUID | None
    entity_type: MemoryEntityType | None
    content: str
    is_active: bool
    created_at: datetime


class SemanticMemorySearchRequest(BaseModel):
    """With an embedding: ranked by cosine distance. Without one (no embedding
    provider configured in ai_agents): scope-filtered, optionally keyword-matched
    on query_text, newest first."""

    model_config = ConfigDict(extra="forbid")

    embedding: list[float] | None = None
    query_text: str | None = Field(default=None, max_length=2_000)
    entity_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    top_k: int = Field(default=5, ge=1, le=20)
    max_distance: float = Field(default=0.5, gt=0, le=2)

    validate_embedding_dim = field_validator("embedding")(_check_embedding)


class SemanticMemorySearchResult(SemanticMemoryResponse):
    distance: float | None = None


class SemanticMemorySupersedeRequest(BaseModel):
    """Staleness post-hook: deactivate older facts about the same entity that
    are semantically close to `content`, then store `content` -- one transaction."""

    model_config = ConfigDict(extra="forbid")

    entity_id: uuid.UUID
    entity_type: MemoryEntityType
    content: str = Field(min_length=1, max_length=2_000)
    embedding: list[float] | None = None
    similarity_threshold: float = Field(default=0.85, gt=0, le=1)

    validate_embedding_dim = field_validator("embedding")(_check_embedding)


class SemanticMemorySupersedeResponse(BaseModel):
    created: SemanticMemoryResponse
    deactivated_ids: list[uuid.UUID]


class SemanticMemoryDedupeResponse(BaseModel):
    deactivated_ids: list[uuid.UUID]
    similarity_threshold: float


class VectorPruneResponse(BaseModel):
    """Pinecone doesn't report how many vectors a filtered delete removed, so
    this reports what was scheduled, not a count."""

    scheduled: bool
    cutoff: datetime | None


class FailedVectorJobResponse(BaseModel):
    """payload is summarized (op + namespace) -- the raw job can carry 768-float
    vectors that are useless in an admin listing."""

    id: uuid.UUID
    op: str
    namespace: str
    error_message: str
    attempts: int
    created_at: datetime
