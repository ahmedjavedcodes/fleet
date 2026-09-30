from fastapi import APIRouter, Depends, File, UploadFile, status

from app.core.deps import require_role
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.upload import ImageUploadResponse
from app.services import upload_service

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])

# Same roles that may report an incident (see api/incidents.py).
_UPLOAD_ROLES = (UserRole.admin, UserRole.fleet_manager, UserRole.driver)


@router.post("/image", response_model=ImageUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_image(
    file: UploadFile = File(...),
    _: User = Depends(require_role(*_UPLOAD_ROLES)),
) -> ImageUploadResponse:
    return ImageUploadResponse(url=upload_service.save_incident_image(file))
