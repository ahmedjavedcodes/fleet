import pytest

from tools import file_parsers
from tools.schemas import FuelReceiptExtraction


class _FakeStructuredModel:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    def invoke(self, messages):
        if self._error:
            raise self._error
        return self._result


class _FakeChatModel:
    def __init__(self, structured: _FakeStructuredModel):
        self._structured = structured

    def with_structured_output(self, schema):
        return self._structured


def test_extract_fuel_receipt_returns_structured_result(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = FuelReceiptExtraction(
        station_name="Shell", receipt_date="2026-01-01", liters=10.5, total_cost=15.75, odometer=1050,
        plate_number="ABC-123",
    )
    fake = _FakeChatModel(_FakeStructuredModel(result=expected))
    monkeypatch.setattr(file_parsers, "get_chat_model", lambda provider: fake)

    result = file_parsers.extract_fuel_receipt(b"fake-jpeg-bytes", "image/jpeg")
    assert result == expected


def test_unsupported_mime_type_rejected_before_calling_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_parsers, "get_chat_model", lambda provider: pytest.fail("must not call the LLM"))

    with pytest.raises(file_parsers.UnsupportedImageTypeError):
        file_parsers.extract_fuel_receipt(b"pdf-bytes", "application/pdf")


def test_model_failure_raises_extraction_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeChatModel(_FakeStructuredModel(error=RuntimeError("blurry receipt")))
    monkeypatch.setattr(file_parsers, "get_chat_model", lambda provider: fake)

    with pytest.raises(file_parsers.ExtractionFailedError):
        file_parsers.extract_fuel_receipt(b"fake-jpeg-bytes", "image/jpeg")
