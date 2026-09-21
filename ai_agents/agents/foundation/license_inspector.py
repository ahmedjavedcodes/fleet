"""LicenseInspectorSubAgent: expiry validation for onboarding driver licenses.

Per fleet-registry-agent.md Behaviour step 6a and Acceptance Criterion 2:
halts the onboarding workflow before any create call when a license is
expired, or when its expiration_date couldn't be extracted at all (an
unreadable expiry is treated the same as a failed extraction, not a pass).
"""

from __future__ import annotations

from datetime import date

from tools.schemas import LicenseExtraction


class ExpiredLicenseError(Exception):
    """Raised when a license's expiration_date is today, in the past, or unreadable."""


def inspect_license(extraction: LicenseExtraction, *, today: date | None = None) -> None:
    """Raises ExpiredLicenseError if the license is expired or has no readable expiry.

    Returns None when the license is valid; callers proceed to the
    duplicate check next.
    """
    reference_date = today or date.today()
    if extraction.expiration_date is None:
        raise ExpiredLicenseError("Could not determine the license's expiration date.")
    if extraction.expiration_date <= reference_date:
        raise ExpiredLicenseError(f"License expired on {extraction.expiration_date.isoformat()}.")
