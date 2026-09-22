from datetime import datetime, timedelta, timezone

import jwt
import pytest

from tools.auth_context import AgentContext, InvalidTokenError, build_context, can_write

_SECRET = "test-secret"


def _make_token(*, sub="user-1", org="org-1", role="admin", exp_delta=timedelta(minutes=30)) -> str:
    payload = {"sub": sub, "org": org, "role": role, "exp": datetime.now(timezone.utc) + exp_delta}
    return jwt.encode(payload, _SECRET, algorithm="HS256")


def test_build_context_extracts_claims() -> None:
    token = _make_token(sub="u1", org="o1", role="fleet_manager")
    context = build_context(token)
    assert context == AgentContext(token=token, user_id="u1", organization_id="o1", role="fleet_manager")


def test_build_context_does_not_require_signature_verification() -> None:
    # signed with a key this module never sees -- decode must still succeed,
    # since the backend (not the agent) is the signature-verification authority.
    token = _make_token()
    context = build_context(token)
    assert context.role == "admin"


def test_missing_token_raises() -> None:
    with pytest.raises(InvalidTokenError):
        build_context(None)


def test_expired_token_raises() -> None:
    token = _make_token(exp_delta=timedelta(minutes=-5))
    with pytest.raises(InvalidTokenError):
        build_context(token)


def test_malformed_token_raises() -> None:
    with pytest.raises(InvalidTokenError):
        build_context("not-a-jwt")


def test_token_missing_required_claim_raises() -> None:
    payload = {"sub": "u1", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}  # no org, no role
    token = jwt.encode(payload, _SECRET, algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        build_context(token)


@pytest.mark.parametrize("role,expected", [("admin", True), ("fleet_manager", True), ("driver", False), ("mechanic", False)])
def test_can_write_by_role(role: str, expected: bool) -> None:
    context = AgentContext(token="t", user_id="u", organization_id="o", role=role)
    assert can_write(context) is expected
