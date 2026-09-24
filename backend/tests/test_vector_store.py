"""Unit tests for the hardened vector layer (Pinecone_Migration_Hardened.md
§1, §3, §4), with the Pinecone client mocked (§6)."""

import logging
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.models.enums import UserRole
from app.services.vector_jobs import VectorJobRunner, execute_job
from app.services.vector_store import (
    OrgScopeGuard,
    PineconeVectorStore,
    VectorSecurityViolation,
    build_rbac_filter,
    org_filter,
    set_vector_store,
    get_vector_store,
    vector_id,
)
from tests.fake_vector_store import matches

ORG = str(uuid.uuid4())
USER = str(uuid.uuid4())


def _user(role=UserRole.driver, org=ORG, user_id=USER):
    return SimpleNamespace(id=uuid.UUID(user_id), organization_id=uuid.UUID(org) if org else None, role=role)


def _meta(**overrides):
    base = {"organization_id": ORG, "memory_id": "m", "scope": "organization", "is_active": True}
    base.update(overrides)
    return base


# ---- §1 centralized RBAC filter ----


def test_filter_always_pins_the_callers_org() -> None:
    f = build_rbac_filter(_user())
    assert f["$and"][0] == {"organization_id": {"$eq": ORG}}
    assert not matches(_meta(organization_id=str(uuid.uuid4())), f)


@pytest.mark.parametrize("role", list(UserRole))
def test_personal_memories_visible_only_to_their_owner_for_every_role(role) -> None:
    f = build_rbac_filter(_user(role=role))
    assert matches(_meta(scope="personal", user_id=USER), f)
    # Corrects the spec's sketch, which let admins/fleet_managers read everyone's personal facts.
    assert not matches(_meta(scope="personal", user_id=str(uuid.uuid4())), f)


@pytest.mark.parametrize("role", list(UserRole))
def test_organization_and_entity_scopes_visible_to_every_role(role) -> None:
    # Corrects the spec's sketch, which hid organization-scope facts from non-managers.
    f = build_rbac_filter(_user(role=role))
    assert matches(_meta(scope="organization"), f)
    assert matches(_meta(scope="entity", entity_id="v1"), f)


def test_extra_clauses_cannot_override_the_org_pin() -> None:
    other_org = str(uuid.uuid4())
    # With the spec's dict.update(), this extra filter would REPLACE the org pin.
    f = build_rbac_filter(_user(), {"organization_id": {"$eq": other_org}})
    assert not matches(_meta(organization_id=other_org), f)
    assert not matches(_meta(), f)  # contradictory -> matches nothing, never the other org


def test_extra_or_clause_cannot_widen_visibility() -> None:
    f = build_rbac_filter(_user(), {"$or": [{"scope": {"$eq": "personal"}}]})
    assert not matches(_meta(scope="personal", user_id=str(uuid.uuid4())), f)


def test_filter_without_org_context_is_a_security_violation(caplog) -> None:
    with caplog.at_level(logging.CRITICAL, logger="fleet.security"), pytest.raises(VectorSecurityViolation):
        build_rbac_filter(_user(org=None))
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)


# ---- §1 runtime enforcer ----


def _guard():
    inner = MagicMock()
    return OrgScopeGuard(inner), inner


def test_guard_refuses_unpinned_query_and_logs_critical(caplog) -> None:
    guard, inner = _guard()
    with caplog.at_level(logging.CRITICAL, logger="fleet.security"), pytest.raises(VectorSecurityViolation):
        guard.query([0.1], 5, {"scope": {"$eq": "organization"}}, "ns")
    inner.query.assert_not_called()
    assert any("SECURITY" in r.getMessage() for r in caplog.records)


def test_guard_refuses_org_pin_hidden_inside_an_or() -> None:
    guard, inner = _guard()
    sneaky = {"$or": [{"organization_id": {"$eq": ORG}}, {"scope": {"$eq": "organization"}}]}
    with pytest.raises(VectorSecurityViolation):
        guard.query([0.1], 5, sneaky, "ns")
    inner.query.assert_not_called()


@pytest.mark.parametrize("pinned", [{"organization_id": ORG}, {"organization_id": {"$eq": ORG}}, org_filter(ORG)])
def test_guard_accepts_top_level_pins(pinned) -> None:
    guard, inner = _guard()
    guard.query([0.1], 5, pinned, "ns")
    inner.query.assert_called_once()


def test_guard_refuses_non_eq_org_operator() -> None:
    guard, inner = _guard()
    with pytest.raises(VectorSecurityViolation):
        guard.delete({"organization_id": {"$ne": ORG}}, "ns")  # "every org except mine"
    inner.delete.assert_not_called()


@pytest.mark.parametrize("filters", [None, {}, {"is_active": {"$eq": False}}])
def test_guard_refuses_unpinned_delete_and_update(filters) -> None:
    guard, inner = _guard()
    with pytest.raises(VectorSecurityViolation):
        guard.delete(filters, "ns")
    with pytest.raises(VectorSecurityViolation):
        guard.update_metadata(filters, {"is_active": False}, "ns")
    inner.delete.assert_not_called()
    inner.update_metadata.assert_not_called()


def test_guard_refuses_rewriting_organization_id() -> None:
    guard, inner = _guard()
    with pytest.raises(VectorSecurityViolation):
        guard.update_metadata(org_filter(ORG), {"organization_id": str(uuid.uuid4())}, "ns")


def test_guard_refuses_upsert_whose_id_and_metadata_disagree() -> None:
    guard, inner = _guard()
    with pytest.raises(VectorSecurityViolation):
        guard.upsert([{"id": vector_id(uuid.uuid4(), "m"), "values": [0.1], "metadata": {"organization_id": ORG}}], "ns")
    with pytest.raises(VectorSecurityViolation):
        guard.upsert([{"id": "m", "values": [0.1], "metadata": {}}], "ns")
    inner.upsert.assert_not_called()


def test_guard_refuses_fetching_another_orgs_ids() -> None:
    guard, inner = _guard()
    with pytest.raises(VectorSecurityViolation):
        guard.fetch([vector_id(ORG, "a"), vector_id(uuid.uuid4(), "b")], ORG, "ns")
    inner.fetch.assert_not_called()


def test_set_vector_store_always_wraps_in_the_guard() -> None:
    set_vector_store(MagicMock())
    assert isinstance(get_vector_store(), OrgScopeGuard)
    set_vector_store(None)


# ---- §4 Pinecone adapter (client mocked) ----


def test_pinecone_query_maps_matches_and_requests_metadata() -> None:
    index = MagicMock()
    index.query.return_value = SimpleNamespace(matches=[SimpleNamespace(id=f"{ORG}#m1", score=0.9, metadata={"scope": "entity"})])
    result = PineconeVectorStore(index).query([0.1], 3, org_filter(ORG), "ns")
    assert result == [{"id": f"{ORG}#m1", "score": 0.9, "metadata": {"scope": "entity"}}]
    assert index.query.call_args.kwargs["include_metadata"] is True
    assert index.query.call_args.kwargs["namespace"] == "ns"


def test_pinecone_fetch_batches_by_100() -> None:
    index = MagicMock()
    index.fetch.side_effect = lambda ids, namespace: SimpleNamespace(
        vectors={i: SimpleNamespace(values=[1.0]) for i in ids}
    )
    ids = [vector_id(ORG, n) for n in range(250)]
    found = PineconeVectorStore(index).fetch(ids, ORG, "ns")
    assert len(found) == 250
    assert [len(c.kwargs["ids"]) for c in index.fetch.call_args_list] == [100, 100, 50]


def test_pinecone_update_and_delete_are_filter_based() -> None:
    index = MagicMock()
    store = PineconeVectorStore(index)
    store.update_metadata(org_filter(ORG), {"is_active": False}, "ns")
    store.delete(org_filter(ORG), "ns")
    assert index.update.call_args.kwargs == {"filter": org_filter(ORG), "set_metadata": {"is_active": False}, "namespace": "ns"}
    assert index.delete.call_args.kwargs == {"filter": org_filter(ORG), "namespace": "ns"}


# ---- §3 retry + DLQ ----


def _runner(store, session):
    sleeps = []
    runner = VectorJobRunner(
        store_provider=lambda: store,
        session_factory=lambda: session,
        executor=MagicMock(),
        sleep=sleeps.append,
    )
    return runner, sleeps


_JOB = {"op": "delete", "namespace": "ns", "filters": org_filter(ORG)}


def test_retry_uses_0_1_4_second_backoff_then_dead_letters() -> None:
    store, session = MagicMock(), MagicMock()
    store.delete.side_effect = ConnectionError("network partition")
    runner, sleeps = _runner(store, session)

    assert runner._run(ORG, _JOB) is False
    assert store.delete.call_count == 3
    assert sleeps == [1.0, 4.0]
    dead = session.add.call_args.args[0]
    assert dead.payload == _JOB and dead.attempts == 3 and "network partition" in dead.error_message
    session.commit.assert_called_once()
    session.close.assert_called_once()


def test_success_on_second_attempt_never_touches_the_dlq() -> None:
    store, session = MagicMock(), MagicMock()
    store.delete.side_effect = [ConnectionError("blip"), None]
    runner, sleeps = _runner(store, session)
    assert runner._run(ORG, _JOB) is True
    assert sleeps == [1.0]
    session.add.assert_not_called()


def test_dlq_write_failure_is_logged_critical_not_raised(caplog) -> None:
    store, session = MagicMock(), MagicMock()
    store.delete.side_effect = ConnectionError("down")
    session.commit.side_effect = RuntimeError("postgres down too")
    runner, _ = _runner(store, session)
    with caplog.at_level(logging.CRITICAL, logger="fleet.vector_jobs"):
        assert runner._run(ORG, _JOB) is False
    assert any("LOST" in r.getMessage() for r in caplog.records)


def test_submit_is_a_noop_without_a_vector_store() -> None:
    runner, _ = _runner(None, MagicMock())
    assert runner.submit(ORG, _JOB) is None
    runner.executor.submit.assert_not_called()


def test_unknown_job_op_is_rejected() -> None:
    with pytest.raises(ValueError):
        execute_job(MagicMock(), {"op": "drop_index", "namespace": "ns"})


class _PineconeError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


def test_missing_namespace_on_update_and_delete_is_a_noop() -> None:
    index = MagicMock()
    index.update.side_effect = _PineconeError(404, "[404] Namespace not found")
    index.delete.side_effect = _PineconeError(404, "[404] Namespace not found")
    store = PineconeVectorStore(index)
    store.update_metadata(org_filter(ORG), {"is_active": False}, "ns")  # must not raise
    store.delete(org_filter(ORG), "ns")


def test_other_pinecone_errors_still_raise_so_the_runner_retries() -> None:
    index = MagicMock()
    index.delete.side_effect = _PineconeError(500, "internal error")
    with pytest.raises(_PineconeError):
        PineconeVectorStore(index).delete(org_filter(ORG), "ns")


def test_unreachable_pinecone_at_init_degrades_instead_of_raising(monkeypatch) -> None:
    import app.services.vector_store as vs

    class _Settings:
        pinecone_api_key = "k"
        pinecone_index = "fleet-memory"

    class _Down:
        def __init__(self, api_key):
            pass

        def describe_index(self, name):
            raise ConnectionError("getaddrinfo failed")

    monkeypatch.setattr("app.core.config.get_settings", lambda: _Settings())
    monkeypatch.setattr("pinecone.Pinecone", _Down)
    monkeypatch.setattr(vs, "_stores", {})

    assert vs.get_vector_store() is None
    assert "fleet-memory" not in vs._stores  # not cached as "absent": the next call retries
