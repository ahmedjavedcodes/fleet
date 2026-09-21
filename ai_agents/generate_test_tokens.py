"""Generate throwaway JWTs for manually testing the Fleet Registry Agent's
RBAC gating (ai_agents/tools/auth_context.py) via index.html.

Not for production use: SECRET_KEY below is a hardcoded mock, and the
tokens are signed with it only so a JWT library will accept the string as
well-formed -- ai_agents/tools/auth_context.build_context() never verifies
the signature anyway (the real backend is the signature authority; see that
module's docstring). Run directly:

    python generate_test_tokens.py

Then paste a printed token into index.html's "JWT Bearer Token" field.

Claim note: ai_agents/tools/auth_context.py and the real backend
(backend/app/core/security.py) both read the org claim as "org", not
"organization_id". This script sets both keys to the same value so the
tokens work against the code as written; if you only need "organization_id"
for some other consumer, "org" is safe to ignore.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt

SECRET_KEY = "mock-local-testing-secret-do-not-use-in-prod"
ALGORITHM = "HS256"
ORGANIZATION_ID = "ORG-123"
ROLES = ["admin", "fleet_manager", "driver", "mechanic"]


def build_token(role: str, *, organization_id: str = ORGANIZATION_ID, user_id: str | None = None) -> str:
    """Build a signed JWT for the given role, expiring 30 days from now."""
    payload = {
        "sub": user_id or str(uuid.uuid4()),
        "organization_id": organization_id,
        "org": organization_id,  # matches the claim name auth_context.py / the backend actually read
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(days=30),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def main() -> None:
    print(f"Organization ID: {ORGANIZATION_ID}")
    print(f"Signed with SECRET_KEY={SECRET_KEY!r} (unused by auth_context.build_context, which never verifies)\n")

    for role in ROLES:
        token = build_token(role)
        print(f"=== {role} ===")
        print(token)
        print()


if __name__ == "__main__":
    main()
