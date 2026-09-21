import pytest

from tools.sanitize import (
    sanitize_license_number,
    sanitize_name,
    sanitize_phone,
    sanitize_plate_number,
    sanitize_vin,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("abc 123", "ABC-123"),
        ("ABC   123", "ABC-123"),
        ("abc_123", "ABC-123"),
        ("  abc-123  ", "ABC-123"),
        (None, ""),
        ("", ""),
    ],
)
def test_sanitize_plate_number(raw, expected) -> None:
    assert sanitize_plate_number(raw) == expected


def test_sanitize_vin_strips_whitespace_and_upper_cases() -> None:
    assert sanitize_vin(" 1hgcm82633a 004352 ") == "1HGCM82633A004352"


def test_sanitize_vin_empty() -> None:
    assert sanitize_vin(None) == ""


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+1 (555) 010-2938", "+15550102938"),
        ("555.010.2938", "5550102938"),
        (None, ""),
    ],
)
def test_sanitize_phone(raw, expected) -> None:
    assert sanitize_phone(raw) == expected


def test_sanitize_name_collapses_whitespace_preserves_case() -> None:
    assert sanitize_name("  John   Doe  ") == "John Doe"


def test_sanitize_license_number() -> None:
    assert sanitize_license_number(" dl 442011 ") == "DL442011"
