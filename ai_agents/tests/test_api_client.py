import httpx
import pytest

from tools.api_client import BackendAPIError, call_backend

_RealClient = httpx.Client


def _patch_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "Client", lambda **kw: _RealClient(transport=transport, **kw))


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
