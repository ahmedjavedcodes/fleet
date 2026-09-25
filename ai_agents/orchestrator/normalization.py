"""Parameter normalization pre-hook, per execution-pre_hooks.md §3.

Runs inside execute_tool, immediately before validate_tool_args (graph.py).
Deterministic Python string transforms keyed by field NAME, applied
recursively -- the fields these rules target (vehicle_plate, phone_number,
month, query_target_date) live nested inside loosely-typed dict fields
(assign_request, trip_fields, ...) on every orchestrator tool schema, not
at its own top level (see the AC 2 correction in
specs/execution-pre_hooks.md: none of the six TOOL_SCHEMAS types
vehicle_plate strictly, so this specific value would not actually have
raised a ToolValidationError even before this hook existed -- normalization
still has real value for Literal-enum case mismatches, e.g.
query_entity="Vehicles", and for downstream data quality, just not for the
literal example given).

Zero-failure tolerance (FR): if a transform raises or can't parse its
input, the ORIGINAL raw value passes through untouched. validate_tool_args
(or, more often, the target sub-agent's own resolution step, which already
re-normalizes plates via tools/sanitize.py) is the real backstop -- this
hook only ever helps, never blocks.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable

# Ordered by specificity -- a plain "%Y-%m" match must not consume a full
# "%Y-%m-%d" string, so full-date formats are tried first.
_FULL_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y")
_MONTH_ONLY_FORMATS = ("%b %Y", "%B %Y", "%Y-%m")

_ISO_FULL_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_MONTH = re.compile(r"^\d{4}-\d{2}$")


def _normalize_plate(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return value.strip().upper()


def _normalize_phone(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    digits = re.sub(r"[^\d+]", "", value)
    if not digits:
        return value
    if not digits.startswith("+"):
        digits = f"+{digits}"
    return digits


def _normalize_date_like(value: Any) -> Any:
    """Shared by month/query_target_date -- returns "%Y-%m-%d" for a
    recognized full date, "%Y-%m" for a recognized month-only string, or
    the original value unchanged if nothing matches (zero-failure
    tolerance)."""
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if _ISO_FULL_DATE.match(stripped) or _ISO_MONTH.match(stripped):
        return stripped  # already ISO-8601 -- leave alone

    for fmt in _FULL_DATE_FORMATS:
        try:
            return datetime.strptime(stripped, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    for fmt in _MONTH_ONLY_FORMATS:
        try:
            return datetime.strptime(stripped, fmt).strftime("%Y-%m")
        except ValueError:
            continue
    return value


_FIELD_NORMALIZERS: dict[str, Callable[[Any], Any]] = {
    "vehicle_plate": _normalize_plate,
    "phone_number": _normalize_phone,
    "month": _normalize_date_like,
    "query_target_date": _normalize_date_like,
}


def _normalize_recursive(obj: Any) -> Any:
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            value = _normalize_recursive(value)
            normalizer = _FIELD_NORMALIZERS.get(key)
            if normalizer is not None:
                try:
                    value = normalizer(value)
                except Exception:  # noqa: BLE001 -- zero-failure tolerance (FR)
                    pass  # value stays whatever it was before this normalizer
            result[key] = value
        return result
    if isinstance(obj, list):
        return [_normalize_recursive(item) for item in obj]
    return obj


def normalize_tool_args(tool_name: str, raw_args: dict[str, Any]) -> dict[str, Any]:
    """Returns a normalized copy of raw_args; never mutates the input.

    tool_name is accepted per the spec's own signature but doesn't
    currently branch behavior -- normalization rules are keyed purely by
    field name, which already disambiguates correctly across all six
    agents (no two agents give a conflicting meaning to the same field
    name)."""
    try:
        return _normalize_recursive(raw_args)
    except Exception:  # noqa: BLE001 -- zero-failure tolerance (FR)
        return raw_args
