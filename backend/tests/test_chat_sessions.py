"""Chat session management on the memory API: listing, auto-titles, rename, full history."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.memory import AgentMessage, AgentSession
from app.models.organization import Organization
from app.services.memory_service import TITLE_MAX_LENGTH, UNTITLED, derive_title
from tests.conftest import auth_headers, make_user


@pytest.fixture()
def alice(db_session: Session, organization: Organization):
    return make_user(db_session, organization, role=UserRole.fleet_manager)


@pytest.fixture()
def bob(db_session: Session, organization: Organization):
    return make_user(db_session, organization, role=UserRole.fleet_manager)


def _new_session(client: TestClient, user) -> str:
    response = client.post("/api/v1/memory/sessions", headers=auth_headers(user))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _say(client: TestClient, user, session_id: str, role: str, content: str) -> None:
    response = client.post(
        f"/api/v1/memory/sessions/{session_id}/messages", json={"role": role, "content": content}, headers=auth_headers(user)
    )
    assert response.status_code == 201, response.text


def _list(client: TestClient, user) -> list[dict]:
    response = client.get("/api/v1/memory/sessions", headers=auth_headers(user))
    assert response.status_code == 200, response.text
    return response.json()


# --- derive_title -------------------------------------------------------------------


def test_derive_title_collapses_whitespace_and_keeps_short_text_as_is() -> None:
    assert derive_title("  Which vehicles\n are   overdue? ") == "Which vehicles are overdue?"


def test_derive_title_cuts_long_text_at_a_word_boundary_within_the_limit() -> None:
    title = derive_title("Please summarise every maintenance job that was recorded for the Toyota Hilux fleet this quarter")
    assert len(title) <= TITLE_MAX_LENGTH
    assert title.endswith("…")
    assert not title.rstrip("…").endswith(" ")
    assert title.startswith("Please summarise every maintenance job")


def test_derive_title_survives_a_single_unbroken_word_and_empty_input() -> None:
    assert len(derive_title("x" * 500)) <= TITLE_MAX_LENGTH
    assert derive_title("   \n ") == UNTITLED


# --- Listing ------------------------------------------------------------------------


def test_a_session_nobody_has_spoken_in_is_not_listed(client: TestClient, alice) -> None:
    _new_session(client, alice)
    assert _list(client, alice) == []


def test_first_user_message_becomes_the_title_and_later_messages_do_not_change_it(client: TestClient, alice) -> None:
    session_id = _new_session(client, alice)
    _say(client, alice, session_id, "user", "Which vehicles are overdue for service?")
    _say(client, alice, session_id, "assistant", "Two vehicles are overdue.")
    _say(client, alice, session_id, "user", "And which are due soon?")

    [row] = _list(client, alice)
    assert row["id"] == session_id
    assert row["title"] == "Which vehicles are overdue for service?"
    assert row["message_count"] == 3


def test_an_assistant_message_alone_does_not_set_a_title(client: TestClient, db_session: Session, alice) -> None:
    session_id = _new_session(client, alice)
    _say(client, alice, session_id, "assistant", "Hello, how can I help?")
    db_session.expire_all()
    assert db_session.get(AgentSession, uuid.UUID(session_id)).title is None


def test_sessions_are_listed_most_recently_active_first(client: TestClient, alice) -> None:
    first = _new_session(client, alice)
    second = _new_session(client, alice)
    _say(client, alice, first, "user", "older conversation")
    _say(client, alice, second, "user", "newer conversation")
    assert [r["id"] for r in _list(client, alice)] == [second, first]

    _say(client, alice, first, "assistant", "a reply arrives in the older one")
    assert [r["id"] for r in _list(client, alice)] == [first, second]


def test_you_only_ever_see_your_own_sessions(client: TestClient, db_session: Session, organization: Organization, alice, bob) -> None:
    mine = _new_session(client, alice)
    _say(client, alice, mine, "user", "alice's question")
    theirs = _new_session(client, bob)
    _say(client, bob, theirs, "user", "bob's question")

    other_org = Organization(id=uuid.uuid4(), name="Other Co", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()
    outsider = make_user(db_session, other_org, role=UserRole.admin)

    assert [r["id"] for r in _list(client, alice)] == [mine]
    assert [r["id"] for r in _list(client, bob)] == [theirs]
    assert _list(client, outsider) == []


def test_a_session_from_before_titles_existed_falls_back_to_its_first_message(client: TestClient, db_session: Session, alice) -> None:
    session_id = _new_session(client, alice)
    _say(client, alice, session_id, "user", "an old question")
    db_session.expire_all()
    session = db_session.get(AgentSession, uuid.UUID(session_id))
    session.title = None
    db_session.commit()

    assert _list(client, alice)[0]["title"] == "an old question"


def test_listing_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/memory/sessions").status_code in (401, 403)


# --- Rename -------------------------------------------------------------------------


def test_rename_changes_the_title_and_trims_whitespace(client: TestClient, alice) -> None:
    session_id = _new_session(client, alice)
    _say(client, alice, session_id, "user", "original question")

    response = client.patch(f"/api/v1/memory/sessions/{session_id}", json={"title": "  Overdue service report  "}, headers=auth_headers(alice))

    assert response.status_code == 200
    assert response.json()["title"] == "Overdue service report"
    assert _list(client, alice)[0]["title"] == "Overdue service report"


def test_a_renamed_title_is_never_overwritten_by_later_messages(client: TestClient, alice) -> None:
    session_id = _new_session(client, alice)
    _say(client, alice, session_id, "user", "original question")
    client.patch(f"/api/v1/memory/sessions/{session_id}", json={"title": "My title"}, headers=auth_headers(alice))

    _say(client, alice, session_id, "user", "a follow up")

    assert _list(client, alice)[0]["title"] == "My title"


def test_renaming_does_not_move_a_conversation_up_the_list(client: TestClient, alice) -> None:
    older = _new_session(client, alice)
    newer = _new_session(client, alice)
    _say(client, alice, older, "user", "older")
    _say(client, alice, newer, "user", "newer")

    client.patch(f"/api/v1/memory/sessions/{older}", json={"title": "Renamed"}, headers=auth_headers(alice))

    assert [r["id"] for r in _list(client, alice)] == [newer, older]


@pytest.mark.parametrize("title", ["", "   ", "x" * 201])
def test_rename_rejects_empty_and_over_long_titles(client: TestClient, alice, title: str) -> None:
    session_id = _new_session(client, alice)
    _say(client, alice, session_id, "user", "hello")
    response = client.patch(f"/api/v1/memory/sessions/{session_id}", json={"title": title}, headers=auth_headers(alice))
    assert response.status_code == 422


def test_rename_rejects_unexpected_fields(client: TestClient, alice) -> None:
    session_id = _new_session(client, alice)
    response = client.patch(
        f"/api/v1/memory/sessions/{session_id}", json={"title": "ok", "running_summary": "sneaky"}, headers=auth_headers(alice)
    )
    assert response.status_code == 422


def test_you_cannot_rename_someone_elses_session(client: TestClient, alice, bob) -> None:
    session_id = _new_session(client, alice)
    _say(client, alice, session_id, "user", "private question")

    response = client.patch(f"/api/v1/memory/sessions/{session_id}", json={"title": "hijacked"}, headers=auth_headers(bob))

    assert response.status_code == 404
    assert _list(client, alice)[0]["title"] == "private question"


def test_renaming_an_unknown_session_is_a_404(client: TestClient, alice) -> None:
    response = client.patch(f"/api/v1/memory/sessions/{uuid.uuid4()}", json={"title": "x"}, headers=auth_headers(alice))
    assert response.status_code == 404


# --- Full transcript ----------------------------------------------------------------


def test_messages_returns_the_whole_transcript_in_order_including_summarised_messages(
    client: TestClient, db_session: Session, alice
) -> None:
    session_id = _new_session(client, alice)
    for role, text in (("user", "one"), ("assistant", "two"), ("user", "three")):
        _say(client, alice, session_id, role, text)
    first = db_session.execute(
        select(AgentMessage).where(AgentMessage.session_id == uuid.UUID(session_id)).order_by(AgentMessage.created_at)
    ).scalars().first()
    first.is_summarized = True
    db_session.commit()

    response = client.get(f"/api/v1/memory/sessions/{session_id}/messages", headers=auth_headers(alice))

    assert response.status_code == 200
    assert [(m["role"], m["content"]) for m in response.json()] == [("user", "one"), ("assistant", "two"), ("user", "three")]
    # The resume path only replays unsummarised messages; the transcript must not.
    context = client.get(f"/api/v1/memory/sessions/{session_id}/context", headers=auth_headers(alice)).json()
    assert len(context["unsummarized_messages"]) == 2


def test_you_cannot_read_someone_elses_transcript(client: TestClient, alice, bob) -> None:
    session_id = _new_session(client, alice)
    _say(client, alice, session_id, "user", "private")
    assert client.get(f"/api/v1/memory/sessions/{session_id}/messages", headers=auth_headers(bob)).status_code == 404
