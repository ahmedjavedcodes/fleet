import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_role
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.memory import (
    AgentMessageAppendResponse,
    AgentMessageCreate,
    AgentMessageResponse,
    AgentSessionContextResponse,
    AgentSessionResponse,
    AgentSessionSummaryUpdate,
    SemanticMemoryCreate,
    SemanticMemoryDedupeResponse,
    SemanticMemoryResponse,
    SemanticMemorySearchRequest,
    SemanticMemorySearchResult,
    SemanticMemorySupersedeRequest,
    SemanticMemorySupersedeResponse,
    FailedVectorJobResponse,
    VectorPruneResponse,
)
from app.services import memory_service

# Every role may use agent memory; per-scope write rules and session ownership
# are enforced in memory_service, since they depend on the row, not just the role.
router = APIRouter(prefix="/api/v1/memory", tags=["agent-memory"])


@router.post("/sessions", response_model=AgentSessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> AgentSessionResponse:
    return AgentSessionResponse.model_validate(memory_service.create_session(db, current_user))


@router.get("/sessions/{session_id}/context", response_model=AgentSessionContextResponse)
def get_session_context(
    session_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> AgentSessionContextResponse:
    session, messages = memory_service.get_context(db, current_user, session_id)
    return AgentSessionContextResponse(
        session=AgentSessionResponse.model_validate(session),
        unsummarized_messages=[AgentMessageResponse.model_validate(m) for m in messages],
    )


@router.post(
    "/sessions/{session_id}/messages", response_model=AgentMessageAppendResponse, status_code=status.HTTP_201_CREATED
)
def append_message(
    session_id: uuid.UUID,
    data: AgentMessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentMessageAppendResponse:
    message, count = memory_service.append_message(db, current_user, session_id, data)
    return AgentMessageAppendResponse(
        message=AgentMessageResponse.model_validate(message),
        unsummarized_count=count,
        needs_summarization=count > memory_service.SUMMARIZATION_TRIGGER,
    )


@router.post("/sessions/{session_id}/summary", response_model=AgentSessionResponse)
def apply_summary(
    session_id: uuid.UUID,
    data: AgentSessionSummaryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentSessionResponse:
    return AgentSessionResponse.model_validate(memory_service.apply_summary(db, current_user, session_id, data))


@router.post("/memories", response_model=SemanticMemoryResponse, status_code=status.HTTP_201_CREATED)
def create_memory(
    data: SemanticMemoryCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> SemanticMemoryResponse:
    return SemanticMemoryResponse.model_validate(memory_service.create_memory(db, current_user, data))


@router.post("/memories/search", response_model=list[SemanticMemorySearchResult])
def search_memories(
    data: SemanticMemorySearchRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[SemanticMemorySearchResult]:
    return [
        SemanticMemorySearchResult.model_validate(memory).model_copy(update={"distance": distance})
        for memory, distance in memory_service.search_memories(db, current_user, data)
    ]


@router.post("/memories/supersede", response_model=SemanticMemorySupersedeResponse, status_code=status.HTTP_201_CREATED)
def supersede_memories(
    data: SemanticMemorySupersedeRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> SemanticMemorySupersedeResponse:
    created, deactivated = memory_service.supersede_entity_memories(db, current_user, data)
    return SemanticMemorySupersedeResponse(created=SemanticMemoryResponse.model_validate(created), deactivated_ids=deactivated)


@router.post("/memories/{memory_id}/deactivate", response_model=SemanticMemoryResponse)
def deactivate_memory(
    memory_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> SemanticMemoryResponse:
    return SemanticMemoryResponse.model_validate(memory_service.deactivate_memory(db, current_user, memory_id))


@router.post("/memories/dedupe", response_model=SemanticMemoryDedupeResponse)
def dedupe_memories(
    current_user: User = Depends(require_role(UserRole.admin)), db: Session = Depends(get_db)
) -> SemanticMemoryDedupeResponse:
    """Retention job for the caller's org. The monthly all-org run is
    `python -m app.jobs.memory_maintenance`."""
    deactivated = memory_service.dedupe_memories(db, current_user.organization_id)
    return SemanticMemoryDedupeResponse(
        deactivated_ids=deactivated, similarity_threshold=memory_service.DEDUPE_SIMILARITY_THRESHOLD
    )


@router.post("/memories/prune", response_model=VectorPruneResponse)
def prune_vectors(
    current_user: User = Depends(require_role(UserRole.admin)), db: Session = Depends(get_db)
) -> VectorPruneResponse:
    cutoff = memory_service.prune_inactive_vectors(db, current_user.organization_id)
    return VectorPruneResponse(scheduled=cutoff is not None, cutoff=cutoff)


@router.get("/vector-jobs/failed", response_model=list[FailedVectorJobResponse])
def list_failed_vector_jobs(
    current_user: User = Depends(require_role(UserRole.admin)), db: Session = Depends(get_db)
) -> list[FailedVectorJobResponse]:
    """The DLQ. Anything here means a memory's vector is missing or stale in
    Pinecone -- the memory itself is still safe in Postgres."""
    return [
        FailedVectorJobResponse(
            id=job.id,
            op=job.payload.get("op", "?"),
            namespace=job.payload.get("namespace", "?"),
            error_message=job.error_message,
            attempts=job.attempts,
            created_at=job.created_at,
        )
        for job in memory_service.list_failed_vector_jobs(db, current_user.organization_id)
    ]


@router.post("/vector-jobs/failed/{job_id}/retry", status_code=status.HTTP_204_NO_CONTENT)
def retry_failed_vector_job(
    job_id: uuid.UUID, current_user: User = Depends(require_role(UserRole.admin)), db: Session = Depends(get_db)
) -> None:
    memory_service.retry_failed_vector_job(db, current_user.organization_id, job_id)
