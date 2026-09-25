from orchestrator.normalization import normalize_tool_args


def test_vehicle_plate_stripped_and_uppercased() -> None:
    result = normalize_tool_args("assignment", {"assign_request": {"vehicle_plate": " abc-123 "}})
    assert result["assign_request"]["vehicle_plate"] == "ABC-123"


def test_ac2_spec_example() -> None:
    # spec's AC 2 wraps vehicle_plate at the top level; verified at the
    # correct real nesting depth too (see test above) since none of the six
    # orchestrator tool schemas actually has a top-level vehicle_plate field
    # -- see normalization.py's module docstring for the AC 2 correction.
    result = normalize_tool_args("assignment", {"vehicle_plate": "xyz-999 "})
    assert result["vehicle_plate"] == "XYZ-999"


def test_phone_number_digits_and_leading_plus() -> None:
    result = normalize_tool_args("foundation", {"provided_fields": {"phone_number": "(555) 010-2938"}})
    assert result["provided_fields"]["phone_number"] == "+5550102938"


def test_phone_number_already_has_plus() -> None:
    result = normalize_tool_args("foundation", {"phone_number": "+1 555 010 2938"})
    assert result["phone_number"] == "+15550102938"


def test_month_natural_language_to_iso() -> None:
    result = normalize_tool_args("insights", {"month": "Jan 2026"})
    assert result["month"] == "2026-01"


def test_month_already_iso_left_alone() -> None:
    result = normalize_tool_args("insights", {"month": "2026-01"})
    assert result["month"] == "2026-01"


def test_query_target_date_natural_language_to_iso() -> None:
    result = normalize_tool_args("assignment", {"query_target_date": "01/15/2026"})
    assert result["query_target_date"] == "2026-01-15"


def test_query_target_date_already_iso_left_alone() -> None:
    result = normalize_tool_args("assignment", {"query_target_date": "2026-01-15"})
    assert result["query_target_date"] == "2026-01-15"


def test_zero_failure_tolerance_gibberish_passes_through_unchanged() -> None:
    result = normalize_tool_args("insights", {"month": "not a date at all"})
    assert result["month"] == "not a date at all"


def test_non_targeted_fields_pass_through_unchanged() -> None:
    result = normalize_tool_args("insights", {"query_entity": "fuel_trends"})
    assert result == {"query_entity": "fuel_trends"}


def test_does_not_mutate_input() -> None:
    original = {"vehicle_plate": " abc "}
    normalize_tool_args("assignment", original)
    assert original == {"vehicle_plate": " abc "}


def test_none_values_pass_through() -> None:
    result = normalize_tool_args("assignment", {"assign_request": None, "query_entity": None})
    assert result == {"assign_request": None, "query_entity": None}


def test_non_string_value_for_targeted_field_passes_through() -> None:
    result = normalize_tool_args("assignment", {"vehicle_plate": 12345})
    assert result["vehicle_plate"] == 12345
