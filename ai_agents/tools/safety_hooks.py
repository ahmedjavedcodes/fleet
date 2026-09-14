"""Safety interceptor for agentic database access.

Per CLAUDE.md directive #3: any agentic SQL execution must pass through a
pre_tool_call hook that strictly enforces read-only queries, protecting the
integrity of manually entered fleet data.
"""

from __future__ import annotations

import re

_WRITE_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "CREATE",
    "GRANT",
    "REVOKE",
    "MERGE",
    "REPLACE",
)

_WRITE_PATTERN = re.compile(r"\b(" + "|".join(_WRITE_KEYWORDS) + r")\b", re.IGNORECASE)


class UnsafeSQLError(Exception):
    """Raised when a generated query would mutate the database."""


def pre_tool_call(sql: str) -> str:
    """Inspect generated SQL before execution; raise if it isn't read-only.

    Returns the original SQL unchanged when it passes the check, so this
    can be used inline: `cursor.execute(pre_tool_call(generated_sql))`.
    """
    stripped = sql.strip().rstrip(";")

    if not stripped:
        raise UnsafeSQLError("Empty SQL is not permitted.")

    if not stripped.upper().startswith(("SELECT", "WITH")):
        raise UnsafeSQLError(f"Only SELECT/WITH queries are permitted, got: {stripped[:40]!r}")

    if ";" in stripped:
        raise UnsafeSQLError("Multiple statements are not permitted.")

    match = _WRITE_PATTERN.search(stripped)
    if match:
        raise UnsafeSQLError(f"Write keyword '{match.group(0)}' is not permitted in read-only mode.")

    return sql
