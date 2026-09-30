import pytest
from pydantic import BaseModel, ConfigDict

from orchestrator.retry import MAX_RETRIES, ToolValidationError, validate_tool_args


class _Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_plate: str
    qty: int


def test_valid_args_pass_through() -> None:
    result = validate_tool_args(_Schema, {"vehicle_plate": "ABC-123", "qty": 5}, attempt=1)
    assert result.vehicle_plate == "ABC-123"


def test_extra_field_raises_with_retry_available() -> None:
    with pytest.raises(ToolValidationError) as exc_info:
        validate_tool_args(_Schema, {"vehicle_plate": "ABC-123", "qty": 5, "bogus_field": True}, attempt=1)
    assert exc_info.value.retries_exhausted is False
    assert "bogus_field" in exc_info.value.observation


def test_missing_field_raises() -> None:
    with pytest.raises(ToolValidationError) as exc_info:
        validate_tool_args(_Schema, {"vehicle_plate": "ABC-123"}, attempt=1)
    assert "qty" in exc_info.value.observation


def test_retries_exhausted_after_max_retries_attempts() -> None:
    with pytest.raises(ToolValidationError) as exc_info:
        validate_tool_args(_Schema, {}, attempt=MAX_RETRIES + 1)
    assert exc_info.value.retries_exhausted is True


def test_not_yet_exhausted_within_max_retries() -> None:
    with pytest.raises(ToolValidationError) as exc_info:
        validate_tool_args(_Schema, {}, attempt=MAX_RETRIES)
    assert exc_info.value.retries_exhausted is False


# --- Phase 1 schema strictness: nested trip/fuel fields and incident fields --------


def test_trip_fields_are_strict_and_fuel_consumed_is_liters() -> None:
    from orchestrator.tool_schemas import FuelToolInput

    trip = {
        "driver_id": "d1", "vehicle_id": "v1", "start_time": "2026-06-01T08:00:00Z", "end_time": "2026-06-01T10:00:00Z",
        "start_odometer": 45000, "end_odometer": 45250,
    }
    ok = FuelToolInput(trip_fields={**trip, "fuel_consumed": 32.5})
    assert ok.trip_fields.fuel_consumed == 32.5
    assert "LITERS" in FuelToolInput.model_json_schema()["$defs"]["TripFields"]["properties"]["fuel_consumed"]["description"]

    with pytest.raises(ToolValidationError):
        validate_tool_args(FuelToolInput, {"trip_fields": {**trip, "fuel_litres": 3}}, attempt=1)  # nested extra key
    with pytest.raises(ToolValidationError):
        validate_tool_args(FuelToolInput, {"trip_fields": {**trip, "fuel_consumed": -2}}, attempt=1)
    with pytest.raises(ToolValidationError):
        validate_tool_args(FuelToolInput, {"fuel_fields": {"slip_no": "S1"}}, attempt=1)


def test_accountability_severity_and_attachment_url_are_validated() -> None:
    from orchestrator.tool_schemas import AccountabilityToolInput

    ok = AccountabilityToolInput(document_type="incident_report", severity="severe", attachment_url="/uploads/incidents/a.jpg")
    assert ok.severity == "severe"
    assert AccountabilityToolInput(attachment_url="https://files.example.com/a.png").attachment_url

    for bad in ({"severity": "high"}, {"attachment_url": "javascript:alert(1)"}, {"attachment_url": "file:///etc/passwd"}):
        with pytest.raises(ToolValidationError):
            validate_tool_args(AccountabilityToolInput, bad, attempt=1)


def test_every_tool_schema_forbids_extra_fields_at_every_level() -> None:
    from pydantic import BaseModel

    from orchestrator.tool_schemas import DOCUMENT_TOOL_NAME, TOOL_SCHEMAS, SearchDocumentsInput, UpdateMemoryInput

    def models(model: type[BaseModel]):
        yield model
        for field in model.model_fields.values():
            for arg in getattr(field.annotation, "__args__", (field.annotation,)):
                if isinstance(arg, type) and issubclass(arg, BaseModel):
                    yield from models(arg)

    for schema in [*TOOL_SCHEMAS.values(), UpdateMemoryInput, SearchDocumentsInput]:
        for model in models(schema):
            assert model.model_config.get("extra") == "forbid", model.__name__
    assert DOCUMENT_TOOL_NAME == "search_documents"
