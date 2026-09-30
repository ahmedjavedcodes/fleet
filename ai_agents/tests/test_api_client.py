import httpx
import pytest

from tools import api_client
from tools.api_client import BackendAPIError, call_backend


def _patch_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    monkeypatch.setattr(api_client, "_client", httpx.Client(transport=httpx.MockTransport(handler)))


def test_the_http_client_is_built_once_and_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Building an httpx.Client loads the SSL trust store (0.4-2s measured on
    Windows); one per call made every backend round trip pay that."""
    built = []
    real = httpx.Client
    monkeypatch.setattr(api_client, "_client", None)
    monkeypatch.setattr(
        httpx, "Client",
        lambda **kw: built.append(1) or real(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])), **kw),
    )

    for _ in range(3):
        call_backend("GET", "/api/v1/vehicles", token="t")

    assert len(built) == 1


def test_per_call_timeout_and_base_url_are_still_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["timeout"] = request.extensions["timeout"]
        return httpx.Response(200, json={})

    _patch_client(monkeypatch, handler)
    monkeypatch.setenv("BACKEND_API_BASE_URL", "http://backend:8000")

    call_backend("GET", "/api/v1/health", timeout=1.5)

    assert seen["url"] == "http://backend:8000/api/v1/health"
    assert seen["timeout"]["read"] == 1.5


def test_get_returns_parsed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v1/vehicles"
        assert request.headers["authorization"] == "Bearer test-token"
        return httpx.Response(200, json=[{"id": "1"}])

    _patch_client(monkeypatch, handler)

    result = call_backend("GET", "/api/v1/vehicles", token="test-token")
    assert result == [{"id": "1"}]


def test_post_sends_json_body(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(201, json={"id": "new"})

    _patch_client(monkeypatch, handler)

    result = call_backend("POST", "/api/v1/vehicles", token="t", json={"plate_number": "ABC-123"})
    assert result == {"id": "new"}
    assert b"ABC-123" in captured["body"]


def test_error_response_raises_with_detail_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "Vehicle with this plate already exists"})

    _patch_client(monkeypatch, handler)

    with pytest.raises(BackendAPIError) as exc_info:
        call_backend("POST", "/api/v1/vehicles", token="t", json={})

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Vehicle with this plate already exists"


def test_no_content_response_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    _patch_client(monkeypatch, handler)

    assert call_backend("DELETE", "/api/v1/vehicles/1", token="t") is None


def test_no_token_omits_authorization_header(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return httpx.Response(200, json=[])

    _patch_client(monkeypatch, handler)

    call_backend("GET", "/api/v1/vehicles")
