import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_role
from app.models.enums import DocumentType
from app.models.user import User
from app.schemas.document import DocumentResponse, DocumentSearchRequest, DocumentSearchResponse
from app.services import document_service

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: UploadFile = File(...),
    document_type: DocumentType = Form(...),
    vehicle_id: uuid.UUID | None = Form(default=None),
    current_user: User = Depends(require_role(*document_service.UPLOAD_ROLES)),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    """202: extraction/summarization/embedding continue in the background --
    poll GET /documents/{id} until status is `ready` (or `failed`). Re-uploading
    the same filename + type replaces the previous version."""
    data = await file.read()
    document = document_service.start_ingest(
        db,
        current_user,
        filename=file.filename or "untitled",
        content_type=file.content_type or "",
        data=data,
        document_type=document_type,
        vehicle_id=vehicle_id,
    )
    return DocumentResponse.model_validate(document)


@router.post("/search", response_model=DocumentSearchResponse)
def search_documents(
    data: DocumentSearchRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> DocumentSearchResponse:
    results, cached = document_service.search(db, current_user, data.query, data.document_types)
    return DocumentSearchResponse(results=results, cached=cached)


@router.get("", response_model=list[DocumentResponse])
def list_documents(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[DocumentResponse]:
    return [DocumentResponse.model_validate(d) for d in document_service.list_documents(db, current_user)]


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: uuid.UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> DocumentResponse:
    return DocumentResponse.model_validate(document_service.get_document(db, current_user, document_id))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: uuid.UUID,
    current_user: User = Depends(require_role(*document_service.UPLOAD_ROLES)),
    db: Session = Depends(get_db),
) -> None:
    document_service.delete_document(db, current_user, document_id)
