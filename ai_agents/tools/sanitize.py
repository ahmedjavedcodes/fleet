"""Text sanitization for vision-extracted fields, before they reach a create tool.

Per fleet-registry-agent.md Functional Requirement 7: extraction output is
never submitted to the backend as-is; it passes through these normalizers
first. Each function is defensive about None/empty input since a field the
vision skill couldn't read should sanitize to an empty string, not raise --
the empty-required-field check happens one layer up, in the sub-agents.
"""

from __future__ import annotations

import re


def sanitize_plate_number(raw: str | None) -> str:
    """Normalize spacing/casing, e.g. 'abc 123' -> 'ABC-123'."""
    if not raw:
        return ""
    collapsed = re.sub(r"[\s_]+", "-", raw.strip())
    collapsed = re.sub(r"-{2,}", "-", collapsed)
    return collapsed.upper().strip("-")


def sanitize_vin(raw: str | None) -> str:
    """VINs are alphanumeric, no separators; upper-case and drop stray whitespace."""
    if not raw:
        return ""
    return re.sub(r"\s+", "", raw.strip()).upper()


def sanitize_phone(raw: str | None) -> str:
    """Keep only digits and a single leading '+', e.g. '+1 (555) 010-2938' -> '+15550102938'."""
    if not raw:
        return ""
    stripped = raw.strip()
    plus = "+" if stripped.startswith("+") else ""
    digits = re.sub(r"\D", "", stripped)
    return f"{plus}{digits}"


def sanitize_name(raw: str | None) -> str:
    """Collapse internal whitespace and trim; preserves casing (names aren't upper-cased)."""
    if not raw:
        return ""
    return re.sub(r"\s+", " ", raw.strip())


def sanitize_license_number(raw: str | None) -> str:
    """Drop internal whitespace and upper-case, e.g. 'dl 442011' -> 'DL442011'."""
    if not raw:
        return ""
    return re.sub(r"\s+", "", raw.strip()).upper()
