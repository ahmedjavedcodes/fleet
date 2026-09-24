"""Live Pinecone tests (Pinecone_Migration_Hardened.md §6) -- opt-in only:

    PINECONE_LIVE_TESTS=1 pytest tests/test_pinecone_live.py

Each run uses a fresh test_ci_<uuid> namespace that is deleted on teardown,
so the suite never touches real memory data and leaves nothing behind. These
prove the filter semantics tests/fake_vector_store.py assumes actually hold
on Pinecone serverless.
"""

import os
import time
import uuid
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.models.enums import UserRole
from app.services.vector_store import OrgScopeGuard, PineconeVectorStore, VectorSecurityViolation, build_rbac_filter, org_filter, vector_id

pytestmark = pytest.mark.skipif(
    os.environ.get("PINECONE_LIVE_TESTS") != "1" or not get_settings().pinecone_api_key,
    reason="live Pinecone tests are opt-in: set PINECONE_LIVE_TESTS=1 and PINECONE_API_KEY",
)

DIM = 768


def _vec(hot: int) -> list[float]:
    values = [0.0] * DIM
    values[hot] = 1.0
    return values


@pytest.fixture(scope="module")
def pinecone_index():
    from pinecone import Pinecone

    settings = get_settings()
    client = Pinecone(api_key=settings.pinecone_api_key)
    return client.Index(host=client.describe_index(settings.pinecone_index).host)


@pytest.fixture
def live_pinecone_namespace(pinecone_index):
    test_namespace = f"test_ci_{uuid.uuid4().hex[:8]}"
    yield test_namespace
    # Correction to the spec's fixture: a test that never writes leaves no
    # namespace behind, and Pinecone answers delete_all on it with a 404.
    try:
        pinecone_index.delete(delete_all=True, namespace=test_namespace)
    except Exception as exc:  # noqa: BLE001
        if getattr(exc, "status_code", None) != 404:
            raise


def test_filter_ops_on_a_never_written_namespace_are_noops(pinecone_index, live_pinecone_namespace) -> None:
    store = OrgScopeGuard(PineconeVectorStore(pinecone_index))
    org = str(uuid.uuid4())
    # Raw Pinecone raises 404 "Namespace not found" for both of these.
    store.update_metadata(org_filter(org), {"is_active": False}, live_pinecone_namespace)
    store.delete(org_filter(org), live_pinecone_namespace)
    assert store.query(_vec(0), 3, org_filter(org), live_pinecone_namespace) == []


def _eventually(check, timeout: float = 30.0):
    """Serverless writes are eventually consistent (spec §5) -- poll."""
    deadline = time.monotonic() + timeout
    while True:
        result = check()
        if result or time.monotonic() > deadline:
            return result
        time.sleep(1.5)


def _metadata(org, memory_id, scope, **extra):
    return {"organization_id": org, "memory_id": memory_id, "scope": scope, "is_active": True, "updated_at": int(time.time()), **extra}


def test_rbac_filter_isolates_orgs_and_personal_memories_on_real_pinecone(pinecone_index, live_pinecone_namespace) -> None:
    store = OrgScopeGuard(PineconeVectorStore(pinecone_index))
    ns = live_pinecone_namespace
    org_a, org_b, me, someone_else = (str(uuid.uuid4()) for _ in range(4))
    store.upsert([
        {"id": vector_id(org_a, "mine"), "values": _vec(0), "metadata": _metadata(org_a, "mine", "personal", user_id=me)},
        {"id": vector_id(org_a, "theirs"), "values": _vec(0), "metadata": _metadata(org_a, "theirs", "personal", user_id=someone_else)},
        {"id": vector_id(org_a, "policy"), "values": _vec(0), "metadata": _metadata(org_a, "policy", "organization")},
        {"id": vector_id(org_b, "foreign"), "values": _vec(0), "metadata": _metadata(org_b, "foreign", "organization")},
    ], ns)

    user = SimpleNamespace(id=uuid.UUID(me), organization_id=uuid.UUID(org_a), role=UserRole.admin)
    rbac = build_rbac_filter(user, {"is_active": {"$eq": True}})
    found = _eventually(lambda: {m["id"] for m in store.query(_vec(0), 10, rbac, ns)} or None)

    assert found == {vector_id(org_a, "mine"), vector_id(org_a, "policy")}


def test_soft_delete_then_prune_by_filter_on_real_pinecone(pinecone_index, live_pinecone_namespace) -> None:
    store = OrgScopeGuard(PineconeVectorStore(pinecone_index))
    ns = live_pinecone_namespace
    org = str(uuid.uuid4())
    store.upsert([
        {"id": vector_id(org, "old"), "values": _vec(1), "metadata": _metadata(org, "old", "organization")},
        {"id": vector_id(org, "keep"), "values": _vec(1), "metadata": _metadata(org, "keep", "organization")},
    ], ns)
    active = org_filter(org, {"is_active": {"$eq": True}})
    assert _eventually(lambda: len(store.query(_vec(1), 10, active, ns)) == 2)

    store.update_metadata(org_filter(org, {"memory_id": {"$in": ["old"]}}), {"is_active": False, "updated_at": 1}, ns)
    assert _eventually(lambda: [m["id"] for m in store.query(_vec(1), 10, active, ns)] == [vector_id(org, "keep")])

    store.delete(org_filter(org, {"is_active": {"$eq": False}}, {"updated_at": {"$lt": int(time.time()) - 86_400}}), ns)
    remaining = _eventually(lambda: (found := store.fetch([vector_id(org, "old"), vector_id(org, "keep")], org, ns))
                            and vector_id(org, "old") not in found and found)
    assert set(remaining) == {vector_id(org, "keep")}


def test_guard_blocks_unpinned_calls_before_they_reach_pinecone(pinecone_index, live_pinecone_namespace) -> None:
    store = OrgScopeGuard(PineconeVectorStore(pinecone_index))
    with pytest.raises(VectorSecurityViolation):
        store.delete({"is_active": {"$eq": False}}, live_pinecone_namespace)
