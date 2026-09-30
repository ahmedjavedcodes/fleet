from pydantic import BaseModel


class ImageUploadResponse(BaseModel):
    # Site-relative path served by the API host (e.g. /uploads/incidents/<uuid>.jpg).
    url: str
