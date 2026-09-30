import pytest

from tools import file_parsers
from tools.schemas import PartLineItem, PartsInvoiceExtraction, WorkOrderExtraction


class _FakeStructuredModel:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.invoked_with = None

    def invoke(self, messages):
        self.invoked_with = messages
        if self._error:
            raise self._error
        return self._result


class _FakeChatModel:
    def __init__(self, structured: _FakeStructuredModel):
        self._structured = structured

    def with_structured_output(self, schema):
        return self._structured


def test_extract_work_order_from_image(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = WorkOrderExtraction(
        issue_description="Brake noise", service_type="brake_service",
        parts_used=[PartLineItem(name_or_sku="Brake Pad", qty=2)], labor_hours=1.5, cost=50.0,
        vehicle_plate="ABC-123", odometer=10000,
    )
    fake = _FakeChatModel(_FakeStructuredModel(result=expected))
    monkeypatch.setattr(file_parsers, "get_vision_model", lambda: fake)

    result = file_parsers.extract_work_order(b"fake-jpeg-bytes", "image/jpeg")
    assert result == expected


def test_extract_work_order_from_text(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = WorkOrderExtraction(issue_description="Oil change due", vehicle_plate="XYZ-999")
    fake = _FakeChatModel(_FakeStructuredModel(result=expected))
    monkeypatch.setattr(file_parsers, "get_vision_model", lambda: fake)

    result = file_parsers.extract_work_order(text="Vehicle XYZ-999 needs an oil change.")
    assert result == expected


def test_extract_work_order_requires_image_or_text() -> None:
    with pytest.raises(ValueError):
        file_parsers.extract_work_order()


def test_extract_parts_invoice_from_image(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = PartsInvoiceExtraction(line_items=[])
    fake = _FakeChatModel(_FakeStructuredModel(result=expected))
    monkeypatch.setattr(file_parsers, "get_vision_model", lambda: fake)

    result = file_parsers.extract_parts_invoice(b"fake-png-bytes", "image/png")
    assert result == expected


def test_extract_parts_invoice_from_text(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = PartsInvoiceExtraction(line_items=[])
    fake = _FakeChatModel(_FakeStructuredModel(result=expected))
    monkeypatch.setattr(file_parsers, "get_vision_model", lambda: fake)

    result = file_parsers.extract_parts_invoice(text="10x Oil Filter @ $5 each")
    assert result == expected


def test_extract_parts_invoice_requires_image_or_text() -> None:
    with pytest.raises(ValueError):
        file_parsers.extract_parts_invoice()


def test_unsupported_mime_type_rejected_before_calling_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_parsers, "get_vision_model", lambda: pytest.fail("must not call the LLM"))

    with pytest.raises(file_parsers.UnsupportedImageTypeError):
        file_parsers.extract_work_order(b"pdf-bytes", "application/pdf")


def test_model_failure_raises_extraction_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeChatModel(_FakeStructuredModel(error=RuntimeError("blurry work order")))
    monkeypatch.setattr(file_parsers, "get_vision_model", lambda: fake)

    with pytest.raises(file_parsers.ExtractionFailedError):
        file_parsers.extract_work_order(b"fake-jpeg-bytes", "image/jpeg")
