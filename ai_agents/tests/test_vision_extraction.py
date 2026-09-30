import pytest

from tools import file_parsers
from tools.schemas import LicenseExtraction, SupplierDocExtraction, VehicleDocExtraction


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


def test_extract_license_data_returns_structured_result(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = LicenseExtraction(first_name="Jane", last_name="Doe", license_number="DL1", expiration_date="2030-01-01")
    fake = _FakeChatModel(_FakeStructuredModel(result=expected))
    monkeypatch.setattr(file_parsers, "get_vision_model", lambda: fake)

    result = file_parsers.extract_license_data(b"fake-jpeg-bytes", "image/jpeg")
    assert result == expected


def test_extract_vehicle_doc_returns_structured_result(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = VehicleDocExtraction(plate_number="ABC-123", make="Ford", model="F150", year=2020, vin="1HG")
    fake = _FakeChatModel(_FakeStructuredModel(result=expected))
    monkeypatch.setattr(file_parsers, "get_vision_model", lambda: fake)

    result = file_parsers.extract_vehicle_doc(b"fake-png-bytes", "image/png")
    assert result == expected


def test_extract_supplier_doc_returns_structured_result(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = SupplierDocExtraction(name="Acme Parts", contact_email="a@acme.com", phone="+15550102938")
    fake = _FakeChatModel(_FakeStructuredModel(result=expected))
    monkeypatch.setattr(file_parsers, "get_vision_model", lambda: fake)

    result = file_parsers.extract_supplier_doc(b"fake-jpeg-bytes", "image/jpeg")
    assert result == expected


def test_unsupported_mime_type_rejected_before_calling_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail():
        raise AssertionError("must not call the LLM for a rejected image type")

    monkeypatch.setattr(file_parsers, "get_vision_model", fail)

    with pytest.raises(file_parsers.UnsupportedImageTypeError):
        file_parsers.extract_license_data(b"pdf-bytes", "application/pdf")


def test_model_failure_raises_extraction_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeChatModel(_FakeStructuredModel(error=RuntimeError("blurry image")))
    monkeypatch.setattr(file_parsers, "get_vision_model", lambda: fake)

    with pytest.raises(file_parsers.ExtractionFailedError):
        file_parsers.extract_vehicle_doc(b"fake-jpeg-bytes", "image/jpeg")
