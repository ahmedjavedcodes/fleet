from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.enums import UserRole
from app.models.organization import Organization
from app.services import upload_service
from tests.conftest import auth_headers, make_user

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture(autouse=True)
def upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))
    return tmp_path


def _post(client: TestClient, user, name: str, content: bytes, content_type: str):
    return client.post(
        "/api/v1/uploads/image", files={"file": (name, content, content_type)}, headers=auth_headers(user)
    )


def test_upload_saves_image_and_returns_servable_url(
    client: TestClient, db_session: Session, organization: Organization, upload_dir: Path
) -> None:
    driver = make_user(db_session, organization, role=UserRole.driver)
    response = _post(client, driver, "crash.jpg", JPEG, "image/jpeg")
    assert response.status_code == 201, response.text
    url = response.json()["url"]
    assert url.startswith("/uploads/incidents/") and url.endswith(".jpg")
    assert (upload_dir / "incidents" / url.rsplit("/", 1)[1]).read_bytes() == JPEG


def test_upload_accepts_png(client: TestClient, db_session: Session, organization: Organization) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    response = _post(client, admin, "scene.png", PNG, "image/png")
    assert response.status_code == 201
    assert response.json()["url"].endswith(".png")


def test_upload_ignores_client_filename(
    client: TestClient, db_session: Session, organization: Organization, upload_dir: Path
) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    response = _post(client, admin, "../../evil.jpg", JPEG, "image/jpeg")
    assert response.status_code == 201
    assert "evil" not in response.json()["url"]
    assert [p.parent for p in upload_dir.rglob("*.jpg")] == [upload_dir / "incidents"]


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b"<html><script>alert(1)</script></html>", "image/jpeg"),  # wrong bytes, right label
        (PNG, "image/jpeg"),  # bytes and label disagree
        (b"GIF89a" + b"\x00" * 16, "image/gif"),  # unsupported type
        (JPEG, "text/html"),
    ],
)
def test_upload_rejects_non_jpeg_png(
    client: TestClient, db_session: Session, organization: Organization, content: bytes, content_type: str
) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    assert _post(client, admin, "x.jpg", content, content_type).status_code == 400


def test_upload_rejects_empty_and_oversized(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    admin = make_user(db_session, organization, role=UserRole.admin)
    assert _post(client, admin, "x.jpg", b"", "image/jpeg").status_code == 400
    too_big = JPEG + b"\x00" * upload_service.MAX_IMAGE_BYTES
    assert _post(client, admin, "x.jpg", too_big, "image/jpeg").status_code == 413


def test_upload_requires_auth_and_a_permitted_role(
    client: TestClient, db_session: Session, organization: Organization
) -> None:
    anonymous = client.post("/api/v1/uploads/image", files={"file": ("x.jpg", JPEG, "image/jpeg")})
    assert anonymous.status_code == 401
    mechanic = make_user(db_session, organization, role=UserRole.mechanic)
    assert _post(client, mechanic, "x.jpg", JPEG, "image/jpeg").status_code == 403
