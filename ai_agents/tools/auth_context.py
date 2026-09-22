"""JWT context extraction for agent-layer RBAC gating and org-scoping.

The agent only ever *reads* the caller's JWT -- to decide which tools to
expose and to tag tool calls with the right organization -- it never
verifies the signature itself. The backend (app.core.security) is the
actual signing/verification authority and independently re-checks the
caller's live role on every request it receives (see backend/app/core/deps.py
require_role, which deliberately re-reads the DB row rather than trusting
the JWT's role claim, so a role change takes effect immediately). This
module is a fail-fast / UX layer, not the security boundary -- see
ai_agents/specs/fleet-registry-agent.md, Acceptance Criterion 6.

Claim names below (`sub`, `org`, `role`) match backend/app/core/security.py
create_access_token exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt

_WRITE_ROLES = frozenset({"admin", "fleet_manager"})


class InvalidTokenError(Exception):
    """Raised when a JWT is missing, malformed, or expired."""


@dataclass(frozen=True)
class AgentContext:
    token: str
    user_id: str
    organization_id: str
    role: str


def build_context(token: str | None) -> AgentContext:
    if not token:
        raise InvalidTokenError("Missing JWT.")

    try:
        # verify_signature=False also disables PyJWT's other default checks
        # (including exp) unless re-enabled explicitly.
        payload = jwt.decode(token, options={"verify_signature": False, "verify_exp": True})
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(f"Malformed or expired JWT: {exc}") from exc

    user_id = payload.get("sub")
    organization_id = payload.get("org")
    role = payload.get("role")
    if not user_id or not organization_id or not role:
        raise InvalidTokenError("JWT is missing required sub/org/role claims.")

    return AgentContext(token=token, user_id=str(user_id), organization_id=str(organization_id), role=str(role))


def can_write(context: AgentContext) -> bool:
    """True if the caller's role is allowed to invoke create_*_tool functions.

    A False here means the agent must refuse before any backend call --
    the backend would independently return 403 for the same caller, but
    this check avoids making that round-trip at all.
    """
    return context.role in _WRITE_ROLES
