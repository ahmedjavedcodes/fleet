from datetime import date

import pytest

from agents.foundation.license_inspector import ExpiredLicenseError, inspect_license
from tools.schemas import LicenseExtraction

_TODAY = date(2026, 9, 21)


def test_future_expiry_passes() -> None:
    inspect_license(LicenseExtraction(expiration_date=date(2027, 1, 1)), today=_TODAY)


def test_past_expiry_raises() -> None:
    with pytest.raises(ExpiredLicenseError):
        inspect_license(LicenseExtraction(expiration_date=date(2025, 1, 1)), today=_TODAY)


def test_expiry_today_raises() -> None:
    with pytest.raises(ExpiredLicenseError):
        inspect_license(LicenseExtraction(expiration_date=_TODAY), today=_TODAY)


def test_missing_expiry_raises() -> None:
    with pytest.raises(ExpiredLicenseError):
        inspect_license(LicenseExtraction(expiration_date=None), today=_TODAY)
