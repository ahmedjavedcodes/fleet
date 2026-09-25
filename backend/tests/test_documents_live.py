"""Live end-to-end document RAG (opt-in, like test_pinecone_live.py):

    PINECONE_LIVE_TESTS=1 pytest tests/test_documents_live.py

Real PyMuPDF extraction, real Pinecone Inference (dense + sparse + rerank),
the real `fleet-documents` dotproduct index, in a throwaway test_ci_<uuid>
namespace deleted on teardown. Table summarization runs too if
GROQ_API_KEY is set in the environment.
"""

import os
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.enums import UserRole
from app.services import document_service
from app.services.rag_inference import PineconeRagInference, set_rag_inference
from app.services.vector_jobs import VectorJobRunner
from app.services.vector_store import PineconeVectorStore, get_document_store, set_document_store
from app.models.memory import EMBEDDING_DIM
from tests.conftest import auth_headers, make_user
from tests.test_document_pipeline import _pdf_with_table
from tests.vector_fixtures import InlineExecutor, _NoClose

pytestmark = pytest.mark.skipif(
    os.environ.get("PINECONE_LIVE_TESTS") != "1" or not get_settings().pinecone_api_key,
    reason="live Pinecone tests are opt-in: set PINECONE_LIVE_TESTS=1 and PINECONE_API_KEY",
)

POLICY = (
    "Fuel policy.\n\n"
    "Drivers must submit fuel receipts within 24 hours of refuelling. Late receipts are not reimbursed.\n\n"
    "Refuelling is only permitted at company-approved stations."
)
INVOICE = "Invoice 4471 from AutoParts Ltd. Four brake pad sets at PKR 12,500 each. Total due PKR 50,000."


def _retry(fn, attempts: int = 10):
    for _ in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 -- this machine's DNS is intermittently flaky
            if "getaddrinfo" not in str(exc):
                raise
            time.sleep(2)
    return fn()


@pytest.fixture
def live(db_session: Session, monkeypatch):
    from pinecone import Pinecone

    settings = get_settings()
    namespace = f"test_ci_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(settings, "documents_namespace", namespace)
    client = Pinecone(api_key=settings.pinecone_api_key)
    index = _retry(lambda: client.Index(host=client.describe_index(settings.pinecone_documents_index).host))
    set_document_store(PineconeVectorStore(index))
    set_rag_inference(PineconeRagInference(client, dense_model=settings.rag_dense_model, sparse_model=settings.rag_sparse_model,
                                           rerank_model=settings.rag_rerank_model, dimension=EMBEDDING_DIM))
    document_service.set_ingest_executor(InlineExecutor())
    document_service.set_ingest_session_factory(lambda: _NoClose(db_session))
    document_service.set_document_runner(VectorJobRunner(store_provider=get_document_store, session_factory=lambda: _NoClose(db_session)))
    if os.environ.get("GROQ_API_KEY"):
        monkeypatch.setattr(settings, "groq_api_key", os.environ["GROQ_API_KEY"])
    yield
    try:
        index.delete(delete_all=True, namespace=namespace)
    except Exception as exc:  # noqa: BLE001
        if getattr(exc, "status_code", None) != 404:
            raise


def _search_until(client, user, query, predicate, timeout=45.0):
    deadline = time.monotonic() + timeout
    while True:
        body = client.post("/api/v1/documents/search", json={"query": query}, headers=auth_headers(user)).json()
        if predicate(body.get("results", [])) or time.monotonic() > deadline:
            return body
        time.sleep(2)


def test_pdf_with_table_is_found_by_meaning_and_reranked(live, client: TestClient, db_session: Session, organization) -> None:
    manager = make_user(db_session, organization, role=UserRole.fleet_manager)
    driver = make_user(db_session, organization, role=UserRole.driver)

    upload = lambda name, data, ctype, dtype: client.post(  # noqa: E731
        "/api/v1/documents/upload", files={"file": (name, data, ctype)}, data={"document_type": dtype}, headers=auth_headers(manager)
    )
    manual = upload("brakes.pdf", _pdf_with_table(), "application/pdf", "manual")
    assert manual.status_code == 202, manual.text
    assert upload("fuel-policy.txt", POLICY.encode(), "text/plain", "policy").status_code == 202
    assert upload("invoice-4471.txt", INVOICE.encode(), "text/plain", "supplier_invoice").status_code == 202

    doc = client.get(f"/api/v1/documents/{manual.json()['id']}", headers=auth_headers(manager)).json()
    assert doc["status"] == "ready" and doc["tables_found"] == 1

    body = _search_until(client, driver, "How often do brake pads need replacing?",
                         lambda r: any("40,000" in h["text"] for h in r))
    hits = body["results"]
    assert hits and "40,000" in hits[0]["text"] and hits[0]["filename"] == "brakes.pdf"
    assert all(h["relevance"] >= get_settings().rag_rerank_threshold for h in hits)
    print("\nlive relevance for brake question:", [(h["filename"], h["relevance"]) for h in hits])

    # Nothing clears the reranker for an unrelated question -> null payload.
    assert client.post("/api/v1/documents/search", json={"query": "What time does the office cafeteria open?"},
                       headers=auth_headers(driver)).json()["results"] == []

    # A driver can never retrieve the supplier invoice; the manager can.
    manager_body = _search_until(client, manager, "What did we pay for brake pad sets?",
                                 lambda r: any(h["filename"] == "invoice-4471.txt" for h in r))
    assert any(h["filename"] == "invoice-4471.txt" for h in manager_body["results"])
    driver_hits = client.post("/api/v1/documents/search", json={"query": "What did we pay for brake pad sets?"},
                              headers=auth_headers(driver)).json()["results"]
    assert all(h["filename"] != "invoice-4471.txt" for h in driver_hits)
