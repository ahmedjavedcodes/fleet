import pytest

from agents.assignment.conflict_checker import (
    AssignmentConflictError,
    check_driver_available,
    check_vehicle_available,
    check_vehicle_has_active_assignment,
)


def test_vehicle_available_when_no_active_assignment() -> None:
    check_vehicle_available([{"released_at": "2026-01-01T17:00:00"}])


def test_vehicle_unavailable_when_active_assignment_exists() -> None:
    with pytest.raises(AssignmentConflictError):
        check_vehicle_available([{"released_at": None}])


def test_vehicle_available_empty_history() -> None:
    check_vehicle_available([])


def test_driver_available_when_no_current_assignment() -> None:
    check_driver_available({"current_assignment": None})


def test_driver_unavailable_when_current_assignment_exists() -> None:
    with pytest.raises(AssignmentConflictError):
        check_driver_available({"current_assignment": {"id": "a1"}})


def test_vehicle_has_active_assignment_passes() -> None:
    check_vehicle_has_active_assignment([{"released_at": None}])


def test_vehicle_has_no_active_assignment_raises() -> None:
    with pytest.raises(AssignmentConflictError):
        check_vehicle_has_active_assignment([{"released_at": "2026-01-01T17:00:00"}])


def test_vehicle_has_no_active_assignment_raises_on_empty_history() -> None:
    with pytest.raises(AssignmentConflictError):
        check_vehicle_has_active_assignment([])
