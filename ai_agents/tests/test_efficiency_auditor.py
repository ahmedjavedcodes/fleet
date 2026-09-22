import pytest

from agents.fuel.efficiency_auditor import OdometerContinuityError, check_odometer_continuity


def test_advancing_odometer_passes() -> None:
    check_odometer_continuity(1050, 1000)


def test_equal_odometer_raises() -> None:
    with pytest.raises(OdometerContinuityError):
        check_odometer_continuity(1000, 1000)


def test_lower_odometer_raises() -> None:
    with pytest.raises(OdometerContinuityError):
        check_odometer_continuity(900, 1000)


def test_missing_odometer_raises() -> None:
    with pytest.raises(OdometerContinuityError):
        check_odometer_continuity(None, 1000)
