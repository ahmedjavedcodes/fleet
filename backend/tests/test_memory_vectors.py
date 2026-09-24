"""Memory API behaviour with a vector store attached (in-memory Pinecone
stand-in behind the real OrgScopeGuard): what reaches the index, the DLQ,
pruning, fail-open reads, and Postgres as the final authority."""

import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.organization import Organization
from app.services.vector_store import vector_id
from tests.conftest import auth_headers, make_user, make_vehicle
from tests.vector_fixtures import vectors  # noqa: F401 -- fixture

NS = "agent-memory"
DIM = 768


def _vec(*hot: int) -> list[float]:
    values = [0.0] * DIM
    for index in hot:
        values[index] = 1.0
    return values


@pytest.fixture()
def admin(db_session: Session, organization: Organization):
    return make_user(db_session, organization, role=UserRole.admin)


@pytest.fixture()
def manager(db_session: Session, organization: Organization):
    return make_user(db_session, organization, role=UserRole.fleet_manager)


@pytest.fixture()
def driver_user(db_session: Session, organization: Organization):
    return make_user(db_session, organization, role=UserRole.driver)


def _store(client, user, **payload) -> dict:
    response = client.post("/api/v1/memory/memories", json=payload, headers=auth_headers(user))
    assert response.status_code == 201, response.text
    return response.json()


def _search(client, user, **payload) -> list[dict]:
    response = client.post("/api/v1/memory/memories/search", json=payload, headers=auth_headers(user))
    assert response.status_code == 200, response.text
    return response.json()


# ---- what reaches Pinecone ----


def test_vector_carries_filter_metadata_but_never_the_memory_text(vectors, client: TestClient, driver_user) -> None:
    memory = _store(client, driver_user, scope="personal", content="Prefers PKR", embedding=_vec(0))
    record = vectors.records(NS)[vector_id(driver_user.organization_id, memory["id"])]

    assert record["metadata"]["organization_id"] == str(driver_user.organization_id)
    assert record["metadata"]["user_id"] == str(driver_user.id)
    assert record["metadata"]["scope"] == "personal" and record["metadata"]["is_active"] is True
    assert "Prefers PKR" not in str(record["metadata"])
    assert None not in record["metadata"].values()  # Pinecone rejects null metadata


def test_memory_without_embedding_never_touches_the_index(vectors, client: TestClient, manager) -> None:
    _store(client, manager, scope="organization", content="Company currency is PKR")
    assert vectors.records(NS) == {}


def test_vector_search_hides_other_users_personal_memories_even_from_admins(
    vectors, client: TestClient, admin, driver_user
) -> None:
    _store(client, driver_user, scope="personal", content="Driver prefers night shifts", embedding=_vec(0))
    _store(client, admin, scope="organization", content="Company currency is PKR", embedding=_vec(0))

    admin_view = [m["content"] for m in _search(client, admin, embedding=_vec(0), top_k=10)]
    assert admin_view == ["Company currency is PKR"]
    driver_view = {m["content"] for m in _search(client, driver_user, embedding=_vec(0), top_k=10)}
    assert driver_view == {"Driver prefers night shifts", "Company currency is PKR"}


# ---- Postgres stays the authority (eventual consistency) ----


def test_deactivated_memory_is_hidden_even_if_pinecone_metadata_is_stale(vectors, client: TestClient, manager) -> None:
    memory = _store(client, manager, scope="organization", content="Old fuel policy", embedding=_vec(0))
    vectors.fail_next = 3  # the soft-delete metadata update never reaches Pinecone
    assert client.post(f"/api/v1/memory/memories/{memory['id']}/deactivate", headers=auth_headers(manager)).status_code == 200

    stale = vectors.records(NS)[vector_id(manager.organization_id, memory["id"])]
    assert stale["metadata"]["is_active"] is True  # Pinecone still thinks it's active...
    assert _search(client, manager, embedding=_vec(0), top_k=10) == []  # ...but it is never returned


def test_search_falls_back_to_keywords_when_pinecone_is_down(vectors, client: TestClient, manager) -> None:
    _store(client, manager, scope="organization", content="Always refuel at Shell stations", embedding=_vec(0))
    vectors.fail_next = 1
    results = _search(client, manager, embedding=_vec(0), query_text="where to refuel", top_k=5)
    assert [r["content"] for r in results] == ["Always refuel at Shell stations"]
    assert results[0]["distance"] is None  # keyword path, not vector path


# ---- §3 dead-letter queue ----


def test_failed_upsert_retries_then_lands_in_the_dlq(vectors, client: TestClient, admin, manager) -> None:
    vectors.fail_next = 3
    memory = _store(client, manager, scope="organization", content="Company currency is PKR", embedding=_vec(0))

    assert vectors.runner.sleeps == [1.0, 4.0]
    assert vectors.records(NS) == {}
    # The user's write still succeeded -- the memory is safe in Postgres.
    assert memory["content"] == "Company currency is PKR"

    jobs = client.get("/api/v1/memory/vector-jobs/failed", headers=auth_headers(admin)).json()
    assert len(jobs) == 1
    assert jobs[0]["op"] == "upsert" and jobs[0]["attempts"] == 3
    assert "simulated Pinecone outage" in jobs[0]["error_message"]


def test_dead_lettered_job_can_be_replayed(vectors, client: TestClient, admin, manager) -> None:
    vectors.fail_next = 3
    memory = _store(client, manager, scope="organization", content="Company currency is PKR", embedding=_vec(0))
    job_id = client.get("/api/v1/memory/vector-jobs/failed", headers=auth_headers(admin)).json()[0]["id"]

    response = client.post(f"/api/v1/memory/vector-jobs/failed/{job_id}/retry", headers=auth_headers(admin))
    assert response.status_code == 204
    assert vector_id(manager.organization_id, memory["id"]) in vectors.records(NS)
    assert client.get("/api/v1/memory/vector-jobs/failed", headers=auth_headers(admin)).json() == []


def test_failed_replay_keeps_the_job_and_counts_the_attempt(vectors, client: TestClient, admin, manager) -> None:
    vectors.fail_next = 4
    _store(client, manager, scope="organization", content="x", embedding=_vec(0))
    job_id = client.get("/api/v1/memory/vector-jobs/failed", headers=auth_headers(admin)).json()[0]["id"]

    assert client.post(f"/api/v1/memory/vector-jobs/failed/{job_id}/retry", headers=auth_headers(admin)).status_code == 502
    assert client.get("/api/v1/memory/vector-jobs/failed", headers=auth_headers(admin)).json()[0]["attempts"] == 4


def test_dlq_is_admin_only_and_org_scoped(vectors, client: TestClient, db_session: Session, admin, manager) -> None:
    vectors.fail_next = 3
    _store(client, manager, scope="organization", content="x", embedding=_vec(0))
    job_id = client.get("/api/v1/memory/vector-jobs/failed", headers=auth_headers(admin)).json()[0]["id"]

    assert client.get("/api/v1/memory/vector-jobs/failed", headers=auth_headers(manager)).status_code == 403
    other_org = Organization(id=uuid.uuid4(), name="Other", slug=f"org-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()
    outsider = make_user(db_session, other_org, role=UserRole.admin)
    assert client.get("/api/v1/memory/vector-jobs/failed", headers=auth_headers(outsider)).json() == []
    assert client.post(f"/api/v1/memory/vector-jobs/failed/{job_id}/retry", headers=auth_headers(outsider)).status_code == 404


# ---- §2 staleness + pruning ----


def test_supersede_soft_deletes_the_old_vector(vectors, client: TestClient, db_session: Session, organization, admin) -> None:
    vehicle = make_vehicle(db_session, organization)
    old = _store(client, admin, scope="entity", content="Transmission slipping", entity_id=str(vehicle.id), entity_type="vehicle", embedding=_vec(0))
    client.post(
        "/api/v1/memory/memories/supersede",
        json={"entity_id": str(vehicle.id), "entity_type": "vehicle", "content": "Transmission replaced", "embedding": _vec(0)},
        headers=auth_headers(admin),
    )
    metadata = vectors.records(NS)[vector_id(organization.id, old["id"])]["metadata"]
    assert metadata["is_active"] is False  # soft delete: excluded by the is_active filter, pruned later
    assert isinstance(metadata["updated_at"], int)


def test_prune_hard_deletes_only_vectors_inactive_for_90_days(vectors, client: TestClient, admin, manager) -> None:
    ancient = _store(client, manager, scope="organization", content="ancient", embedding=_vec(0))
    recent = _store(client, manager, scope="organization", content="recent", embedding=_vec(1))
    live = _store(client, manager, scope="organization", content="live", embedding=_vec(2))
    for memory in (ancient, recent):
        client.post(f"/api/v1/memory/memories/{memory['id']}/deactivate", headers=auth_headers(manager))
    ninety_one_days_ago = int(time.time()) - 91 * 86_400
    vectors.records(NS)[vector_id(manager.organization_id, ancient["id"])]["metadata"]["updated_at"] = ninety_one_days_ago

    response = client.post("/api/v1/memory/memories/prune", headers=auth_headers(admin))
    assert response.status_code == 200 and response.json()["scheduled"] is True

    remaining = set(vectors.records(NS))
    assert vector_id(manager.organization_id, ancient["id"]) not in remaining
    assert vector_id(manager.organization_id, recent["id"]) in remaining
    assert vector_id(manager.organization_id, live["id"]) in remaining


def test_prune_never_reaches_another_orgs_vectors(vectors, client: TestClient, db_session: Session, admin) -> None:
    other_org = Organization(id=uuid.uuid4(), name="Other", slug=f"org-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()
    foreign_id = vector_id(other_org.id, uuid.uuid4())
    vectors.records(NS)[foreign_id] = {
        "values": _vec(0),
        "metadata": {"organization_id": str(other_org.id), "is_active": False, "updated_at": 0, "scope": "organization"},
    }
    client.post("/api/v1/memory/memories/prune", headers=auth_headers(admin))
    assert foreign_id in vectors.records(NS)


def test_prune_without_vector_store_schedules_nothing(client: TestClient, admin) -> None:
    assert client.post("/api/v1/memory/memories/prune", headers=auth_headers(admin)).json() == {"scheduled": False, "cutoff": None}
