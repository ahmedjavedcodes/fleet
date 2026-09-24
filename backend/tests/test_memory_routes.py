import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.organization import Organization
from tests.conftest import auth_headers, make_user, make_vehicle

DIM = 768


def _vec(*hot: int) -> list[float]:
    """Unit-ish vector with 1.0 at the given indices -- cosine distance between
    _vec(0) and _vec(1) is exactly 1, between _vec(0) and _vec(0) exactly 0."""
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
def mechanic(db_session: Session, organization: Organization):
    return make_user(db_session, organization, role=UserRole.mechanic)


@pytest.fixture()
def driver_user(db_session: Session, organization: Organization):
    return make_user(db_session, organization, role=UserRole.driver)


@pytest.fixture()
def other_org(db_session: Session) -> Organization:
    org = Organization(id=uuid.uuid4(), name="Other Fleet", slug=f"org-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.commit()
    return org


def _new_session(client: TestClient, user) -> str:
    response = client.post("/api/v1/memory/sessions", headers=auth_headers(user))
    assert response.status_code == 201
    return response.json()["id"]


def _append(client: TestClient, user, session_id: str, content: str, role: str = "user"):
    return client.post(
        f"/api/v1/memory/sessions/{session_id}/messages",
        json={"role": role, "content": content},
        headers=auth_headers(user),
    )


# --- Short-term memory -----------------------------------------------------------


def test_sixth_message_flags_needs_summarization(client: TestClient, driver_user) -> None:
    session_id = _new_session(client, driver_user)
    for i in range(5):
        body = _append(client, driver_user, session_id, f"message {i}").json()
        assert body["needs_summarization"] is False
    body = _append(client, driver_user, session_id, "message 5").json()
    assert body["unsummarized_count"] == 6
    assert body["needs_summarization"] is True


def test_session_is_private_to_its_owner(client: TestClient, admin, manager) -> None:
    session_id = _new_session(client, manager)
    # Even an admin in the same org gets 404, not 403 -- session ids can't be probed.
    response = client.get(f"/api/v1/memory/sessions/{session_id}/context", headers=auth_headers(admin))
    assert response.status_code == 404
    assert _append(client, admin, session_id, "hi").status_code == 404


def test_context_returns_unsummarized_messages_in_order(client: TestClient, manager) -> None:
    session_id = _new_session(client, manager)
    for content in ("first", "second", "third"):
        _append(client, manager, session_id, content)
    body = client.get(f"/api/v1/memory/sessions/{session_id}/context", headers=auth_headers(manager)).json()
    assert [m["content"] for m in body["unsummarized_messages"]] == ["first", "second", "third"]
    assert body["session"]["running_summary"] == ""
    assert body["session"]["summary_version"] == 0


def test_apply_summary_folds_messages_and_bumps_version(client: TestClient, manager) -> None:
    session_id = _new_session(client, manager)
    ids = [_append(client, manager, session_id, f"m{i}").json()["message"]["id"] for i in range(3)]

    response = client.post(
        f"/api/v1/memory/sessions/{session_id}/summary",
        json={"message_ids": ids[:2], "running_summary": "User asked about m0 and m1.", "expected_summary_version": 0},
        headers=auth_headers(manager),
    )
    assert response.status_code == 200
    assert response.json()["summary_version"] == 1

    context = client.get(f"/api/v1/memory/sessions/{session_id}/context", headers=auth_headers(manager)).json()
    assert [m["content"] for m in context["unsummarized_messages"]] == ["m2"]
    assert context["session"]["running_summary"] == "User asked about m0 and m1."


def test_stale_summary_version_is_rejected(client: TestClient, manager) -> None:
    session_id = _new_session(client, manager)
    ids = [_append(client, manager, session_id, f"m{i}").json()["message"]["id"] for i in range(4)]
    headers = auth_headers(manager)
    url = f"/api/v1/memory/sessions/{session_id}/summary"

    first = client.post(url, json={"message_ids": ids[:2], "running_summary": "A", "expected_summary_version": 0}, headers=headers)
    assert first.status_code == 200
    # A second worker that also read version 0 loses, even for different messages.
    second = client.post(url, json={"message_ids": ids[2:], "running_summary": "B", "expected_summary_version": 0}, headers=headers)
    assert second.status_code == 409


def test_already_summarized_messages_cannot_be_folded_twice(client: TestClient, manager) -> None:
    session_id = _new_session(client, manager)
    ids = [_append(client, manager, session_id, f"m{i}").json()["message"]["id"] for i in range(2)]
    headers = auth_headers(manager)
    url = f"/api/v1/memory/sessions/{session_id}/summary"

    assert client.post(url, json={"message_ids": ids, "running_summary": "A", "expected_summary_version": 0}, headers=headers).status_code == 200
    again = client.post(url, json={"message_ids": ids, "running_summary": "A again", "expected_summary_version": 1}, headers=headers)
    assert again.status_code == 409


# --- Long-term vault: writes & scope RBAC ------------------------------------------


def test_driver_can_store_personal_memory(client: TestClient, driver_user) -> None:
    response = client.post(
        "/api/v1/memory/memories", json={"scope": "personal", "content": "Prefers PKR"}, headers=auth_headers(driver_user)
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == str(driver_user.id)
    assert "embedding" not in body


def test_driver_cannot_store_organization_memory(client: TestClient, driver_user) -> None:
    response = client.post(
        "/api/v1/memory/memories", json={"scope": "organization", "content": "Use PKR"}, headers=auth_headers(driver_user)
    )
    assert response.status_code == 403


def test_mechanic_can_store_entity_memory_for_own_org_vehicle(
    client: TestClient, db_session: Session, organization: Organization, mechanic
) -> None:
    vehicle = make_vehicle(db_session, organization)
    response = client.post(
        "/api/v1/memory/memories",
        json={"scope": "entity", "content": "Transmission slips in 3rd", "entity_id": str(vehicle.id), "entity_type": "vehicle"},
        headers=auth_headers(mechanic),
    )
    assert response.status_code == 201


def test_entity_memory_for_another_orgs_vehicle_is_404(
    client: TestClient, db_session: Session, other_org: Organization, manager
) -> None:
    foreign_vehicle = make_vehicle(db_session, other_org)
    response = client.post(
        "/api/v1/memory/memories",
        json={"scope": "entity", "content": "x", "entity_id": str(foreign_vehicle.id), "entity_type": "vehicle"},
        headers=auth_headers(manager),
    )
    assert response.status_code == 404


def test_entity_scope_requires_entity_fields(client: TestClient, manager) -> None:
    response = client.post("/api/v1/memory/memories", json={"scope": "entity", "content": "x"}, headers=auth_headers(manager))
    assert response.status_code == 422


def test_wrong_embedding_dimension_is_rejected(client: TestClient, manager) -> None:
    response = client.post(
        "/api/v1/memory/memories",
        json={"scope": "organization", "content": "x", "embedding": [0.1, 0.2]},
        headers=auth_headers(manager),
    )
    assert response.status_code == 422


# --- Long-term vault: reads --------------------------------------------------------


def _store(client: TestClient, user, **payload) -> dict:
    response = client.post("/api/v1/memory/memories", json=payload, headers=auth_headers(user))
    assert response.status_code == 201, response.text
    return response.json()


def _search(client: TestClient, user, **payload) -> list[dict]:
    response = client.post("/api/v1/memory/memories/search", json=payload, headers=auth_headers(user))
    assert response.status_code == 200, response.text
    return response.json()


def test_personal_memories_are_invisible_to_other_users(
    client: TestClient, db_session: Session, organization: Organization, manager, driver_user
) -> None:
    _store(client, driver_user, scope="personal", content="Driver prefers night shifts")
    _store(client, manager, scope="organization", content="Company currency is PKR")

    manager_view = [m["content"] for m in _search(client, manager, top_k=20)]
    assert "Company currency is PKR" in manager_view
    assert "Driver prefers night shifts" not in manager_view

    driver_view = [m["content"] for m in _search(client, driver_user, top_k=20)]
    assert "Driver prefers night shifts" in driver_view
    assert "Company currency is PKR" in driver_view


def test_other_organizations_memories_are_never_returned(
    client: TestClient, db_session: Session, other_org: Organization, manager
) -> None:
    outsider = make_user(db_session, other_org, role=UserRole.fleet_manager)
    _store(client, outsider, scope="organization", content="Outsider secret policy", embedding=_vec(0))

    results = _search(client, manager, embedding=_vec(0), top_k=20)
    assert all(r["content"] != "Outsider secret policy" for r in results)


def test_vector_search_ranks_by_cosine_distance(client: TestClient, manager) -> None:
    _store(client, manager, scope="organization", content="near", embedding=_vec(0))
    _store(client, manager, scope="organization", content="middle", embedding=_vec(0, 1))
    _store(client, manager, scope="organization", content="far", embedding=_vec(5))

    results = _search(client, manager, embedding=_vec(0), top_k=5, max_distance=0.5)
    assert [r["content"] for r in results] == ["near", "middle"]  # "far" is beyond max_distance
    assert results[0]["distance"] == pytest.approx(0.0, abs=1e-6)


def test_keyword_fallback_without_embedding(client: TestClient, manager) -> None:
    _store(client, manager, scope="organization", content="Always refuel at Shell stations")
    _store(client, manager, scope="organization", content="Weekly safety briefing on Mondays")

    results = _search(client, manager, query_text="Which stations should we refuel at?", top_k=5)
    assert [r["content"] for r in results] == ["Always refuel at Shell stations"]
    assert results[0]["distance"] is None


def test_keyword_fallback_ignores_like_wildcards(client: TestClient, manager) -> None:
    _store(client, manager, scope="organization", content="Always refuel at Shell stations")
    _store(client, manager, scope="organization", content="Weekly safety briefing on Mondays")
    # "%" must not act as a match-everything wildcard -- only "refuel" is a keyword here.
    results = _search(client, manager, query_text="refuel%%", top_k=5)
    assert [r["content"] for r in results] == ["Always refuel at Shell stations"]


# --- Staleness, deactivation, retention --------------------------------------------


def test_supersede_deactivates_similar_facts_about_same_entity_only(
    client: TestClient, db_session: Session, organization: Organization, mechanic
) -> None:
    vehicle = make_vehicle(db_session, organization)
    other_vehicle = make_vehicle(db_session, organization)
    stale = _store(client, mechanic, scope="entity", content="Transmission slipping", entity_id=str(vehicle.id), entity_type="vehicle", embedding=_vec(0))
    unrelated = _store(client, mechanic, scope="entity", content="Tyres worn", entity_id=str(vehicle.id), entity_type="vehicle", embedding=_vec(9))
    other = _store(client, mechanic, scope="entity", content="Transmission slipping", entity_id=str(other_vehicle.id), entity_type="vehicle", embedding=_vec(0))

    response = client.post(
        "/api/v1/memory/memories/supersede",
        json={"entity_id": str(vehicle.id), "entity_type": "vehicle", "content": "Transmission replaced", "embedding": _vec(0)},
        headers=auth_headers(mechanic),
    )
    assert response.status_code == 201
    assert response.json()["deactivated_ids"] == [stale["id"]]

    active = {m["id"] for m in _search(client, mechanic, top_k=20)}
    assert stale["id"] not in active
    assert unrelated["id"] in active
    assert other["id"] in active


def test_supersede_without_embedding_deactivates_nothing(
    client: TestClient, db_session: Session, organization: Organization, mechanic
) -> None:
    vehicle = make_vehicle(db_session, organization)
    _store(client, mechanic, scope="entity", content="Transmission slipping", entity_id=str(vehicle.id), entity_type="vehicle")
    response = client.post(
        "/api/v1/memory/memories/supersede",
        json={"entity_id": str(vehicle.id), "entity_type": "vehicle", "content": "Transmission replaced"},
        headers=auth_headers(mechanic),
    )
    assert response.status_code == 201
    assert response.json()["deactivated_ids"] == []


def test_driver_cannot_supersede_entity_memories(
    client: TestClient, db_session: Session, organization: Organization, driver_user
) -> None:
    vehicle = make_vehicle(db_session, organization)
    response = client.post(
        "/api/v1/memory/memories/supersede",
        json={"entity_id": str(vehicle.id), "entity_type": "vehicle", "content": "x"},
        headers=auth_headers(driver_user),
    )
    assert response.status_code == 403


def test_deactivate_respects_scope_write_roles(client: TestClient, manager, driver_user) -> None:
    org_fact = _store(client, manager, scope="organization", content="Company currency is PKR")
    own_fact = _store(client, driver_user, scope="personal", content="Prefers night shifts")

    assert client.post(f"/api/v1/memory/memories/{org_fact['id']}/deactivate", headers=auth_headers(driver_user)).status_code == 403
    response = client.post(f"/api/v1/memory/memories/{own_fact['id']}/deactivate", headers=auth_headers(driver_user))
    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_cannot_deactivate_another_users_personal_memory(client: TestClient, manager, driver_user) -> None:
    own_fact = _store(client, driver_user, scope="personal", content="Prefers night shifts")
    assert client.post(f"/api/v1/memory/memories/{own_fact['id']}/deactivate", headers=auth_headers(manager)).status_code == 404


def test_dedupe_keeps_oldest_and_deactivates_near_duplicates(client: TestClient, admin, manager) -> None:
    original = _store(client, manager, scope="organization", content="Currency is PKR", embedding=_vec(0))
    duplicate = _store(client, manager, scope="organization", content="The currency is PKR", embedding=_vec(0))
    distinct = _store(client, manager, scope="organization", content="Weekly briefing Mondays", embedding=_vec(3))

    response = client.post("/api/v1/memory/memories/dedupe", headers=auth_headers(admin))
    assert response.status_code == 200
    assert response.json()["deactivated_ids"] == [duplicate["id"]]

    active = {m["id"] for m in _search(client, manager, top_k=20)}
    assert original["id"] in active and distinct["id"] in active


def test_dedupe_does_not_merge_across_scopes(client: TestClient, admin, manager) -> None:
    _store(client, manager, scope="organization", content="Currency is PKR", embedding=_vec(0))
    _store(client, manager, scope="personal", content="Currency is PKR", embedding=_vec(0))
    assert client.post("/api/v1/memory/memories/dedupe", headers=auth_headers(admin)).json()["deactivated_ids"] == []


def test_dedupe_is_admin_only(client: TestClient, manager) -> None:
    assert client.post("/api/v1/memory/memories/dedupe", headers=auth_headers(manager)).status_code == 403
