"""Document RAG API (hybrid-document-rag-pipeline.md §1, §3) against an
in-memory dotproduct store behind the real OrgScopeGuard and a deterministic
inference fake. Background ingestion runs inline."""

import uuid
from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.document import Document, DocumentChunk, DocumentIngestFailure
from app.models.enums import DocumentStatus, DocumentType, UserRole
from app.models.memory import FailedVectorJob
from app.models.organization import Organization
from app.services import document_service
from app.services.rag_inference import set_rag_inference
from app.services.vector_jobs import VectorJobRunner
from app.services.vector_store import get_document_store, set_document_store
from tests.conftest import auth_headers, make_user
from tests.fake_rag_inference import FakeRagInference
from tests.fake_vector_store import FakeVectorStore
from tests.vector_fixtures import InlineExecutor, _NoClose
from tests.test_document_pipeline import _pdf_with_table

NS = get_settings().documents_namespace

BRAKES = (
    "Brake pads on the Hilux must be inspected every 10,000 km.\n\n"
    "Brake pads are replaced at 40,000 km or below 3 mm thickness."
)
FUEL_POLICY = "Drivers must submit fuel receipts within 24 hours of refuelling.\n\nLate receipts are not reimbursed."
INVOICE = "Invoice 4471 from AutoParts: brake pad sets at PKR 12,500 each, total PKR 50,000."


@pytest.fixture()
def rag(db_session: Session) -> Generator[dict, None, None]:
    store = FakeVectorStore(metric="dotproduct")
    inference = FakeRagInference()
    set_document_store(store)
    set_rag_inference(inference)
    document_service.set_ingest_executor(InlineExecutor())
    document_service.set_ingest_session_factory(lambda: _NoClose(db_session))
    sleeps: list[float] = []
    document_service.set_document_runner(
        VectorJobRunner(store_provider=get_document_store, session_factory=lambda: _NoClose(db_session), sleep=sleeps.append)
    )
    yield {"store": store, "inference": inference, "sleeps": sleeps}
    document_service.set_ingest_executor(InlineExecutor())


@pytest.fixture()
def users(db_session: Session, organization: Organization) -> dict:
    return {role: make_user(db_session, organization, role=role) for role in UserRole}


def _upload(client, user, name, content, document_type, content_type="text/plain", **extra):
    data = content.encode() if isinstance(content, str) else content
    return client.post(
        "/api/v1/documents/upload",
        files={"file": (name, data, content_type)},
        data={"document_type": document_type, **extra},
        headers=auth_headers(user),
    )


def _search(client, user, query, **extra) -> dict:
    response = client.post("/api/v1/documents/search", json={"query": query, **extra}, headers=auth_headers(user))
    assert response.status_code == 200, response.text
    return response.json()


# ---- §1.1 RBAC ----


@pytest.mark.parametrize("role", [UserRole.driver, UserRole.mechanic])
def test_only_admins_and_fleet_managers_can_upload(rag, client: TestClient, users, role) -> None:
    assert _upload(client, users[role], "brakes.txt", BRAKES, "manual").status_code == 403


def test_upload_is_accepted_then_ingested_to_ready(rag, client: TestClient, db_session: Session, users) -> None:
    response = _upload(client, users[UserRole.fleet_manager], "brakes.txt", BRAKES, "manual")
    assert response.status_code == 202
    body = response.json()
    assert body["version"] == 1

    document = client.get(f"/api/v1/documents/{body['id']}", headers=auth_headers(users[UserRole.fleet_manager])).json()
    assert document["status"] == "ready" and document["chunk_count"] >= 1
    stored = rag["store"].records(NS)
    assert stored and all(vid.startswith(f"{users[UserRole.fleet_manager].organization_id}#") for vid in stored)
    assert all("chunk_text" not in rec["metadata"] and "Brake" not in str(rec["metadata"]) for rec in stored.values())
    assert all(rec["sparse_values"]["indices"] for rec in stored.values())  # dual encoding


@pytest.mark.parametrize(
    "role, visible",
    [
        (UserRole.admin, {"brakes.txt", "fuel.txt", "invoice.txt", "legal.txt", "incident.txt"}),
        (UserRole.fleet_manager, {"brakes.txt", "fuel.txt", "invoice.txt", "incident.txt"}),
        (UserRole.mechanic, {"brakes.txt", "fuel.txt"}),  # incident_report withheld: no mechanic<->vehicle assignment exists
        (UserRole.driver, {"brakes.txt", "fuel.txt"}),
    ],
)
def test_role_to_document_type_matrix(rag, client: TestClient, users, role, visible) -> None:
    admin = users[UserRole.admin]
    _upload(client, admin, "brakes.txt", BRAKES, "manual")
    _upload(client, admin, "fuel.txt", FUEL_POLICY, "policy")
    _upload(client, admin, "invoice.txt", INVOICE, "supplier_invoice")
    _upload(client, admin, "legal.txt", "Brake pads liability clause for fuel receipts and invoices.", "legal")
    _upload(client, admin, "incident.txt", "Brake pads failed on the Hilux; fuel receipts and invoice attached.", "incident_report")

    listed = {d["filename"] for d in client.get("/api/v1/documents", headers=auth_headers(users[role])).json()}
    assert listed == visible
    found = {hit["filename"] for q in ("brake pads", "fuel receipts", "invoice brake pad sets")
             for hit in _search(client, users[role], q)["results"]}
    assert found <= visible


def test_requested_types_are_intersected_with_role_scope(rag, client: TestClient, users) -> None:
    _upload(client, users[UserRole.admin], "invoice.txt", INVOICE, "supplier_invoice")
    # A driver explicitly asking for invoices still gets nothing.
    assert _search(client, users[UserRole.driver], "brake pad sets invoice", document_types=["supplier_invoice"])["results"] == []


def test_other_organizations_documents_are_never_returned(rag, client: TestClient, db_session: Session, users) -> None:
    other_org = Organization(id=uuid.uuid4(), name="Other", slug=f"org-{uuid.uuid4().hex[:8]}")
    db_session.add(other_org)
    db_session.commit()
    outsider = make_user(db_session, other_org, role=UserRole.admin)
    _upload(client, outsider, "brakes.txt", BRAKES, "manual")
    assert _search(client, users[UserRole.admin], "brake pads replaced")["results"] == []


# ---- §3 retrieval ----


def test_hybrid_search_then_rerank_returns_the_relevant_chunk(rag, client: TestClient, users) -> None:
    manager = users[UserRole.fleet_manager]
    _upload(client, manager, "brakes.txt", BRAKES, "manual")
    _upload(client, manager, "fuel.txt", FUEL_POLICY, "policy")

    hits = _search(client, manager, "when are brake pads replaced")["results"]
    assert hits and hits[0]["filename"] == "brakes.txt"
    assert all(h["relevance"] >= get_settings().rag_rerank_threshold for h in hits)


def test_nothing_above_threshold_returns_a_null_payload(rag, client: TestClient, users) -> None:
    _upload(client, users[UserRole.admin], "brakes.txt", BRAKES, "manual")
    assert _search(client, users[UserRole.admin], "quarterly cafeteria menu")["results"] == []


def test_at_most_three_chunks_are_returned(rag, client: TestClient, users) -> None:
    text = "\n\n".join(f"Brake pad note {i}: brake pads wear on route {i}." for i in range(12))
    _upload(client, users[UserRole.admin], "notes.txt", text, "manual")
    assert len(_search(client, users[UserRole.admin], "brake pads wear")["results"]) <= 3


def test_semantic_cache_serves_repeat_queries_and_upload_invalidates_it(rag, client: TestClient, users) -> None:
    manager = users[UserRole.fleet_manager]
    _upload(client, manager, "brakes.txt", BRAKES, "manual")

    first = _search(client, manager, "brake pads replaced at what km")
    second = _search(client, manager, "brake pads replaced at what km")
    assert first["cached"] is False and second["cached"] is True
    assert second["results"] == first["results"]

    _upload(client, manager, "fuel.txt", FUEL_POLICY, "policy")  # org content changed
    assert _search(client, manager, "brake pads replaced at what km")["cached"] is False


def test_cache_is_not_shared_across_roles(rag, client: TestClient, users) -> None:
    _upload(client, users[UserRole.admin], "invoice.txt", INVOICE, "supplier_invoice")
    assert _search(client, users[UserRole.fleet_manager], "brake pad sets price")["results"]
    driver_view = _search(client, users[UserRole.driver], "brake pad sets price")
    assert driver_view == {"results": [], "cached": False}


def test_empty_results_are_never_cached(rag, client: TestClient, users) -> None:
    manager = users[UserRole.fleet_manager]
    assert _search(client, manager, "brake pads replaced")["results"] == []
    _upload(client, manager, "brakes.txt", BRAKES, "manual")
    assert _search(client, manager, "brake pads replaced")["results"]


# ---- §1.2 versioning, lease, pre-purge ----


def test_reupload_replaces_the_previous_version(rag, client: TestClient, users) -> None:
    manager = users[UserRole.fleet_manager]
    _upload(client, manager, "brakes.txt", BRAKES, "manual")
    second = _upload(client, manager, "brakes.txt", "Brake pads are now replaced at 35,000 km.", "manual").json()
    assert second["version"] == 2

    assert all(rec["metadata"]["version"] == 2 for rec in rag["store"].records(NS).values())
    texts = " ".join(h["text"] for h in _search(client, manager, "brake pads replaced")["results"])
    assert "35,000" in texts and "40,000" not in texts


def test_concurrent_upload_of_the_same_document_gets_429(rag, client: TestClient, db_session: Session, users) -> None:
    manager = users[UserRole.fleet_manager]
    doc_id = _upload(client, manager, "brakes.txt", BRAKES, "manual").json()["id"]
    document = db_session.get(Document, uuid.UUID(doc_id))
    document.status = DocumentStatus.processing
    document.processing_started_at = datetime.now(timezone.utc)
    db_session.commit()

    assert _upload(client, manager, "brakes.txt", BRAKES, "manual").status_code == 429


def test_expired_lease_does_not_block_a_new_upload(rag, client: TestClient, db_session: Session, users) -> None:
    manager = users[UserRole.fleet_manager]
    doc_id = _upload(client, manager, "brakes.txt", BRAKES, "manual").json()["id"]
    document = db_session.get(Document, uuid.UUID(doc_id))
    document.status = DocumentStatus.processing
    document.processing_started_at = datetime.now(timezone.utc) - timedelta(seconds=document_service.LEASE_SECONDS + 1)
    db_session.commit()

    assert _upload(client, manager, "brakes.txt", BRAKES, "manual").status_code == 202


def test_stale_version_vectors_are_never_served(rag, client: TestClient, users) -> None:
    manager = users[UserRole.fleet_manager]
    _upload(client, manager, "brakes.txt", BRAKES, "manual")
    records = rag["store"].records(NS)
    # Simulate a late-finishing v0 ingestion that slipped a vector in.
    vid, rec = next(iter(records.items()))
    records[vid.replace("#v1#", "#v0#")] = {**rec, "metadata": {**rec["metadata"], "version": 0, "chunk_index": 999}}
    hits = _search(client, manager, "brake pads inspected")["results"]
    assert all(h["chunk_index"] != 999 for h in hits)


def test_pre_purge_failure_rejects_the_upload(rag, client: TestClient, db_session: Session, users) -> None:
    rag["store"].fail_next = 1  # the blocking pre-purge delete
    response = _upload(client, users[UserRole.admin], "brakes.txt", BRAKES, "manual")
    assert response.status_code == 503
    document = db_session.execute(select(Document)).scalar_one()
    assert document.status == DocumentStatus.failed


# ---- failures ----


def test_unreadable_pdf_marks_the_document_failed(rag, client: TestClient, db_session: Session, users) -> None:
    response = _upload(client, users[UserRole.admin], "broken.pdf", b"%PDF-1.4 not really a pdf", "manual", "application/pdf")
    assert response.status_code == 202
    document = client.get(f"/api/v1/documents/{response.json()['id']}", headers=auth_headers(users[UserRole.admin])).json()
    assert document["status"] == "failed" and document["error_message"]
    assert db_session.execute(select(DocumentIngestFailure.stage)).scalars().all() == ["ingest"]


def test_real_pdf_with_table_is_ingested(rag, client: TestClient, db_session: Session, users) -> None:
    response = _upload(client, users[UserRole.admin], "brakes.pdf", _pdf_with_table(), "manual", "application/pdf")
    document = client.get(f"/api/v1/documents/{response.json()['id']}", headers=auth_headers(users[UserRole.admin])).json()
    assert document["status"] == "ready" and document["tables_found"] == 1
    chunks = db_session.execute(select(DocumentChunk.text)).scalars().all()
    assert any("|Brake pads|40,000|" in c for c in chunks)


def test_table_summary_failure_is_dead_lettered_and_falls_back(rag, client: TestClient, db_session: Session, users, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "groq_api_key", "test-key")
    monkeypatch.setattr(document_service, "groq_completion", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("groq down")))
    monkeypatch.setattr("app.services.table_summarizer.time.sleep", lambda s: None)

    response = _upload(client, users[UserRole.admin], "brakes.pdf", _pdf_with_table(), "manual", "application/pdf")
    document = client.get(f"/api/v1/documents/{response.json()['id']}", headers=auth_headers(users[UserRole.admin])).json()
    assert document["status"] == "ready" and document["tables_summarized"] == 0  # Markdown fallback still indexed
    failure = db_session.execute(select(DocumentIngestFailure)).scalar_one()
    assert failure.stage == "table_summary" and "groq down" in failure.error_message


def test_failed_vector_upsert_is_dead_lettered_and_replayable_to_the_documents_index(rag, client: TestClient, db_session: Session, users) -> None:
    admin = users[UserRole.admin]
    _upload(client, admin, "brakes.txt", BRAKES, "manual")
    # Re-upload with every upsert attempt failing (the pre-purge delete still succeeds).
    original_upsert = rag["store"].upsert
    attempts = []

    def _failing_upsert(vectors, namespace):
        attempts.append(1)
        raise ConnectionError("pinecone write timeout")

    rag["store"].upsert = _failing_upsert
    doc_id = _upload(client, admin, "brakes.txt", "Brake pads replaced at 35,000 km.", "manual").json()["id"]
    assert len(attempts) == 3 and rag["sleeps"][-2:] == [1.0, 4.0]
    document = client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers(admin)).json()
    assert document["status"] == "failed" and "dead-lettered" in document["error_message"]

    job = db_session.execute(select(FailedVectorJob)).scalar_one()
    assert job.payload["store"] == "documents"
    rag["store"].upsert = original_upsert
    replay = client.post(f"/api/v1/memory/vector-jobs/failed/{job.id}/retry", headers=auth_headers(admin))
    assert replay.status_code == 204
    assert rag["store"].records(NS)  # replayed into the documents index, not agent memory


def test_search_failure_is_a_503_not_unreranked_results(client: TestClient, db_session: Session, users) -> None:
    store = FakeVectorStore(metric="dotproduct")
    set_document_store(store)
    set_rag_inference(FakeRagInference(rerank_fail=True))
    document_service.set_ingest_executor(InlineExecutor())
    document_service.set_ingest_session_factory(lambda: _NoClose(db_session))
    _upload(client, users[UserRole.admin], "brakes.txt", BRAKES, "manual")
    response = client.post("/api/v1/documents/search", json={"query": "brake pads replaced"}, headers=auth_headers(users[UserRole.admin]))
    assert response.status_code == 503


def test_not_configured_is_a_503(client: TestClient, users) -> None:
    assert _upload(client, users[UserRole.admin], "brakes.txt", BRAKES, "manual").status_code == 503
    response = client.post("/api/v1/documents/search", json={"query": "brake pads"}, headers=auth_headers(users[UserRole.admin]))
    assert response.status_code == 503


@pytest.mark.parametrize(
    "name, content, content_type, expected",
    [("x.docx", b"PK..", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", 415), ("x.txt", b"", "text/plain", 422)],
)
def test_upload_validation(rag, client: TestClient, users, name, content, content_type, expected) -> None:
    assert _upload(client, users[UserRole.admin], name, content, "manual", content_type).status_code == expected


def test_oversized_upload_is_rejected(rag, client: TestClient, users, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "rag_max_upload_mb", 0)
    assert _upload(client, users[UserRole.admin], "brakes.txt", BRAKES, "manual").status_code == 413


def test_vehicle_from_another_org_is_rejected(rag, client: TestClient, users) -> None:
    response = _upload(client, users[UserRole.admin], "brakes.txt", BRAKES, "manual", vehicle_id=str(uuid.uuid4()))
    assert response.status_code == 404


# ---- delete ----


def test_delete_purges_vectors_and_rows(rag, client: TestClient, users) -> None:
    admin = users[UserRole.admin]
    doc_id = _upload(client, admin, "brakes.txt", BRAKES, "manual").json()["id"]
    assert client.delete(f"/api/v1/documents/{doc_id}", headers=auth_headers(users[UserRole.driver])).status_code == 403
    assert client.delete(f"/api/v1/documents/{doc_id}", headers=auth_headers(admin)).status_code == 204
    assert rag["store"].records(NS) == {}
    assert client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers(admin)).status_code == 404
    assert _search(client, admin, "brake pads replaced")["results"] == []
