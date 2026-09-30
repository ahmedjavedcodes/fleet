import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DocumentStatus, DocumentType

MAX_DOCUMENT_IDS = 10


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    document_type: DocumentType
    vehicle_id: uuid.UUID | None
    status: DocumentStatus
    version: int
    size_bytes: int
    chunk_count: int
    tables_found: int
    tables_summarized: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class DocumentSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=3, max_length=500)
    # Optional narrowing -- always intersected with what the caller's role may see.
    document_types: list[DocumentType] | None = None
    # Restrict the search to exactly these documents (the chat's "@" mentions). Ids the caller may not see, or that
    # are not ready, simply match nothing -- this can only narrow a search, never widen it.
    document_ids: list[uuid.UUID] | None = Field(default=None, max_length=MAX_DOCUMENT_IDS)


class DocumentSearchHit(BaseModel):
    document_id: uuid.UUID
    filename: str
    document_type: DocumentType
    chunk_index: int
    text: str
    relevance: float


class DocumentChunkOut(BaseModel):
    """One stored passage, for the document preview."""

    chunk_index: int
    text: str


class DocumentSearchResponse(BaseModel):
    """`results` is empty (the spec's "null payload") when nothing cleared the
    reranker threshold -- callers must not treat that as an error."""

    results: list[DocumentSearchHit]
    cached: bool
