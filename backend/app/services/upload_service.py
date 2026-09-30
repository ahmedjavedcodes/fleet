import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.core.config import get_settings

INCIDENT_IMAGE_URL_PREFIX = "/uploads/incidents"
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# Extension is derived from the sniffed bytes, never from the client filename or
# Content-Type, so a mislabelled upload cannot land as an executable/HTML file.
_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
)


def _sniff(content: bytes) -> tuple[str, str] | None:
    """(mime type, extension) from the file's own bytes, or None."""
    for magic, mime, ext in _SIGNATURES:
        if content.startswith(magic):
            return mime, ext
    # WebP is a RIFF container: "RIFF", a 4-byte size, then "WEBP".
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


def incident_image_dir() -> Path:
    return Path(get_settings().upload_dir) / "incidents"


def save_incident_image(file: UploadFile) -> str:
    content = file.file.read(MAX_IMAGE_BYTES + 1)
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded image is empty")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Image must be 5 MB or smaller")

    match = _sniff(content)
    if match is None or file.content_type != match[0]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only JPEG, PNG and WebP images are allowed")

    directory = incident_image_dir()
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4()}{match[1]}"
    (directory / name).write_bytes(content)
    return f"{INCIDENT_IMAGE_URL_PREFIX}/{name}"
