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
