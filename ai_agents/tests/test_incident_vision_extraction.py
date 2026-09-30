import pytest

from tools import file_parsers
from tools.schemas import IncidentExtraction


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


def test_extract_incident_report_from_image(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = IncidentExtraction(
        incident_date="2026-01-01", location="Main St", severity="moderate", incident_type="damage",
        vehicle_plate="ABC-123", driver_name="Jane Doe", damage_description="Rear bumper dent",
    )
    fake = _FakeChatModel(_FakeStructuredModel(result=expected))
    monkeypatch.setattr(file_parsers, "get_vision_model", lambda: fake)

    result = file_parsers.extract_incident_report(b"fake-jpeg-bytes", "image/jpeg")
    assert result == expected


def test_extract_incident_report_from_text(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = IncidentExtraction(vehicle_plate="XYZ-999", damage_description="Scratch on door")
    fake = _FakeChatModel(_FakeStructuredModel(result=expected))
    monkeypatch.setattr(file_parsers, "get_vision_model", lambda: fake)

    result = file_parsers.extract_incident_report(text="Vehicle XYZ-999 got a scratch on the door.")
    assert result == expected


def test_extract_incident_report_requires_image_or_text() -> None:
    with pytest.raises(ValueError):
        file_parsers.extract_incident_report()


def test_unsupported_mime_type_rejected_before_calling_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_parsers, "get_vision_model", lambda: pytest.fail("must not call the LLM"))

    with pytest.raises(file_parsers.UnsupportedImageTypeError):
        file_parsers.extract_incident_report(b"pdf-bytes", "application/pdf")


def test_model_failure_raises_extraction_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeChatModel(_FakeStructuredModel(error=RuntimeError("blurry report")))
    monkeypatch.setattr(file_parsers, "get_vision_model", lambda: fake)

    with pytest.raises(file_parsers.ExtractionFailedError):
        file_parsers.extract_incident_report(b"fake-jpeg-bytes", "image/jpeg")
