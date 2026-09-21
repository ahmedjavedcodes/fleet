from agents.foundation.duplicate_checker import (
    find_duplicate_driver,
    find_duplicate_supplier,
    find_duplicate_vehicle,
)
from tools.auth_context import AgentContext

_CTX = AgentContext(token="t", user_id="u1", organization_id="o1", role="admin")


def test_find_duplicate_vehicle_matches_case_and_space_insensitively() -> None:
    existing = [{"id": "1", "plate_number": "ABC-123"}]
    result = find_duplicate_vehicle(_CTX, "abc-123", get_vehicles=lambda ctx: existing)
    assert result == existing[0]


def test_find_duplicate_vehicle_no_match_returns_none() -> None:
    existing = [{"id": "1", "plate_number": "ABC-123"}]
    assert find_duplicate_vehicle(_CTX, "XYZ-999", get_vehicles=lambda ctx: existing) is None


def test_find_duplicate_vehicle_empty_plate_returns_none_without_listing() -> None:
    def fail(ctx):
        raise AssertionError("should not list when plate is empty")

    assert find_duplicate_vehicle(_CTX, "", get_vehicles=fail) is None


def test_find_duplicate_driver_matches_on_license_number() -> None:
    existing = [{"id": "1", "license_number": "DL442011"}]
    assert find_duplicate_driver(_CTX, "dl442011", get_drivers=lambda ctx: existing) == existing[0]


def test_find_duplicate_supplier_matches_case_insensitively() -> None:
    existing = [{"id": "1", "name": "Acme Parts"}]
    assert find_duplicate_supplier(_CTX, "acme parts", get_suppliers=lambda ctx: existing) == existing[0]


def test_find_duplicate_supplier_no_match() -> None:
    existing = [{"id": "1", "name": "Acme Parts"}]
    assert find_duplicate_supplier(_CTX, "Other Co", get_suppliers=lambda ctx: existing) is None
