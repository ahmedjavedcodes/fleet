"""Recursive PII/secret redaction, per fleet-live-observer.md FR 5.

Applied to every input_payload/observation before a ToolTrace/LLMTrace is
instantiated (audit_schemas.py's docstring, AC 1) -- this module never
raises on malformed input; an object it can't recurse into (bytes, an
unknown type) is passed through key-matching only, never crashes the
caller (consistent with FR 6's failure-isolation principle, though the
actual try/except swallow lives in callbacks.py, not here).
"""

from __future__ import annotations

from typing import Any

# Matched case-insensitively against dict keys at any nesting depth.
# token/access_token/jwt added beyond the spec's example list -- the
# caller's own bearer token is at least as sensitive as a license number,
# and it flows through orchestrator state (auth_context) the same way.
DEFAULT_BLOCKLIST = frozenset({
    "license_number",
    "phone_number",
    "document_text",
    "image_bytes",
    "token",
    "access_token",
    "jwt",
})

_REDACTED = "[REDACTED]"


def redact_payload(value: Any, *, blocklist: frozenset[str] = DEFAULT_BLOCKLIST) -> Any:
    """Returns a redacted deep copy; never mutates the input."""
    if isinstance(value, dict):
        return {
            key: (_REDACTED if str(key).lower() in blocklist else redact_payload(val, blocklist=blocklist))
            for key, val in value.items()
        }
    if isinstance(value, (list, tuple)):
        redacted = [redact_payload(item, blocklist=blocklist) for item in value]
        return type(value)(redacted) if isinstance(value, tuple) else redacted
    return value
