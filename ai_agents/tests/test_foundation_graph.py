"""End-to-end tests for the Fleet Registry Agent's LangGraph orchestration.

Each test is named after the Acceptance Criterion it covers in
ai_agents/specs/fleet-registry-agent.md. Only the vision extraction step is
faked (no live Groq call); everything downstream -- RBAC gating, duplicate
checks, field bridging, backend calls -- runs through the real
mcp_server.foundation_tools / tools.auth_context code, with
mcp_server.foundation_tools.call_backend swapped for an in-memory fake
backend so no live Postgres/FastAPI process is required.
"""

from datetime import date, datetime, timedelta, timezone

import jwt
import pytest

from agents.foundation.graph import FoundationAgentDeps, get_compiled_foundation_graph
from mcp_server import foundation_tools as ft
from tools import file_parsers
from tools.api_client import BackendAPIError
from tools.file_parsers import ExtractionFailedError
from tools.schemas import LicenseExtraction, SupplierDocExtraction, VehicleDocExtraction


def _token(role: str, org: str = "org-1") -> str:
    payload = {"sub": "user-1", "org": org, "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, "irrelevant-signing-key", algorithm="HS256")


class _FakeBackend:
    """In-memory stand-in for mcp_server.foundation_tools.call_backend."""

    def __init__(self) -> None:
        self.vehicles: list[dict] = []
        self.drivers: list[dict] = []
        self.suppliers: list[dict] = []
        self.create_vehicle_calls = 0
        self.create_driver_calls = 0
        self.create_supplier_calls = 0
        self.force_409_on_vehicle_create = False

    def __call__(self, method, path, *, token=None, json=None, params=None, timeout=10.0):
        if method == "GET" and path == "/api/v1/vehicles":
            return list(self.vehicles)
        if method == "GET" and path == "/api/v1/drivers":
            return list(self.drivers)
        if method == "GET" and path == "/api/v1/suppliers":
            return list(self.suppliers)

        if method == "POST" and path == "/api/v1/vehicles":
            self.create_vehicle_calls += 1
            if self.force_409_on_vehicle_create:
                # Simulate a concurrent writer inserting the same plate
                # between this agent's pre-check and its create call.
                self.vehicles.append({"id": "concurrent", "plate_number": json["plate_number"]})
                raise BackendAPIError(409, "duplicate plate")
            record = {"id": "v-new", **json}
            self.vehicles.append(record)
            return record

        if method == "POST" and path == "/api/v1/drivers":
            self.create_driver_calls += 1
            record = {"id": "d-new", **json}
            self.drivers.append(record)
            return record

        if method == "POST" and path == "/api/v1/suppliers":
            self.create_supplier_calls += 1
            record = {"id": "s-new", **json}
            self.suppliers.append(record)
            return record

        raise AssertionError(f"unexpected backend call: {method} {path}")


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> _FakeBackend:
    fake = _FakeBackend()
    monkeypatch.setattr(ft, "call_backend", fake)
    return fake


def test_ac1_valid_license_creates_driver(backend: _FakeBackend) -> None:
    extraction = LicenseExtraction(
        first_name="Jane", last_name="Doe", license_number="DL1", phone_number="555-010-2938",
        expiration_date=date(2030, 1, 1),
    )
    deps = FoundationAgentDeps(extract_license=lambda img, mime: extraction)
    graph = get_compiled_foundation_graph(deps)

    state = graph.invoke(
        {"token": _token("admin"), "document_type": "license", "image_bytes": b"jpeg", "mime_type": "image/jpeg"}
    )

    assert state["stage"] == "done"
    assert state["created_record"]["full_name"] == "Jane Doe"
    assert backend.create_driver_calls == 1


def test_ac2_expired_license_halts_before_create(backend: _FakeBackend) -> None:
    extraction = LicenseExtraction(
        first_name="Jane", last_name="Doe", license_number="DL1", phone_number="555",
        expiration_date=date(2020, 1, 1),
    )
    deps = FoundationAgentDeps(extract_license=lambda img, mime: extraction)
    graph = get_compiled_foundation_graph(deps)

    state = graph.invoke(
        {"token": _token("admin"), "document_type": "license", "image_bytes": b"jpeg", "mime_type": "image/jpeg"}
    )

    assert state["stage"] == "halted"
    assert "expired" in state["halt_reason"].lower()
    assert backend.create_driver_calls == 0


def test_ac3_duplicate_plate_halts_before_create(backend: _FakeBackend) -> None:
    backend.vehicles = [{"id": "existing", "plate_number": "ABC-123"}]
    extraction = VehicleDocExtraction(plate_number="abc 123", make="Ford", model="F150", year=2020, vin="1HG")
    deps = FoundationAgentDeps(extract_vehicle=lambda img, mime: extraction)
    graph = get_compiled_foundation_graph(deps)

    state = graph.invoke(
        {
            "token": _token("admin"),
            "document_type": "vehicle_doc",
            "image_bytes": b"jpeg",
            "mime_type": "image/jpeg",
            "provided_fields": {"fuel_type": "diesel"},
        }
    )

    assert state["stage"] == "halted"
    assert state["duplicate_of"]["id"] == "existing"
    assert backend.create_vehicle_calls == 0


def test_ac4_backend_409_race_reports_conflict_without_retry(backend: _FakeBackend) -> None:
    backend.force_409_on_vehicle_create = True
    extraction = VehicleDocExtraction(plate_number="ABC-123", make="Ford", model="F150", year=2020, vin="1HG")
    deps = FoundationAgentDeps(extract_vehicle=lambda img, mime: extraction)
    graph = get_compiled_foundation_graph(deps)

    state = graph.invoke(
        {
            "token": _token("admin"),
            "document_type": "vehicle_doc",
            "image_bytes": b"jpeg",
            "mime_type": "image/jpeg",
            "provided_fields": {"fuel_type": "diesel"},
        }
    )

    assert state["stage"] == "halted"
    assert state["duplicate_of"]["id"] == "concurrent"
    assert backend.create_vehicle_calls == 1  # no retry of the create call


def test_ac5_missing_fuel_type_asks_then_creates_on_resume(backend: _FakeBackend) -> None:
    extraction = VehicleDocExtraction(plate_number="ABC-123", make="Ford", model="F150", year=2020, vin="1HG")
    deps = FoundationAgentDeps(extract_vehicle=lambda img, mime: extraction)
    graph = get_compiled_foundation_graph(deps)

    first = graph.invoke(
        {"token": _token("admin"), "document_type": "vehicle_doc", "image_bytes": b"jpeg", "mime_type": "image/jpeg"}
    )
    assert first["stage"] == "awaiting_missing_field"
    assert first["missing_fields"] == ["fuel_type"]
    assert backend.create_vehicle_calls == 0

    second = graph.invoke({**first, "provided_fields": {"fuel_type": "diesel"}})
    assert second["stage"] == "done"
    assert second["created_record"]["fuel_type"] == "diesel"
    assert backend.create_vehicle_calls == 1


def test_ac6_driver_role_refused_before_backend_create(backend: _FakeBackend) -> None:
    extraction = VehicleDocExtraction(plate_number="ABC-123", make="Ford", model="F150", year=2020, vin="1HG")
    deps = FoundationAgentDeps(extract_vehicle=lambda img, mime: extraction)
    graph = get_compiled_foundation_graph(deps)

    state = graph.invoke(
        {
            "token": _token("driver"),
            "document_type": "vehicle_doc",
            "image_bytes": b"jpeg",
            "mime_type": "image/jpeg",
            "provided_fields": {"fuel_type": "diesel"},
        }
    )

    assert state["stage"] == "halted"
    assert "permit" in state["halt_reason"].lower()
    assert backend.create_vehicle_calls == 0


def test_ac7_query_returns_results_for_any_role(backend: _FakeBackend) -> None:
    backend.vehicles = [{"id": "v1", "organization_id": "org-1"}]
    deps = FoundationAgentDeps()
    graph = get_compiled_foundation_graph(deps)

    state = graph.invoke({"token": _token("mechanic"), "query_entity": "vehicles"})

    assert state["stage"] == "done"
    assert state["query_result"] == backend.vehicles


def test_ac8_extraction_failure_halts_without_creating(backend: _FakeBackend) -> None:
    def failing_extractor(img, mime):
        raise ExtractionFailedError("could not read the vehicle document")

    deps = FoundationAgentDeps(extract_vehicle=failing_extractor)
    graph = get_compiled_foundation_graph(deps)

    state = graph.invoke(
        {"token": _token("admin"), "document_type": "vehicle_doc", "image_bytes": b"blurry", "mime_type": "image/jpeg"}
    )

    assert state["stage"] == "halted"
    assert backend.create_vehicle_calls == 0


def test_ac9_unsupported_file_type_rejected_before_vision_call(
    backend: _FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(file_parsers, "get_vision_model", lambda: pytest.fail("must not call the LLM"))
    deps = FoundationAgentDeps(extract_vehicle=file_parsers.extract_vehicle_doc)
    graph = get_compiled_foundation_graph(deps)

    state = graph.invoke(
        {
            "token": _token("admin"),
            "document_type": "vehicle_doc",
            "image_bytes": b"pdf-bytes",
            "mime_type": "application/pdf",
        }
    )

    assert state["stage"] == "halted"
    assert "jpeg" in state["halt_reason"].lower() or "png" in state["halt_reason"].lower()
    assert backend.create_vehicle_calls == 0


def test_ac10_supplier_onboarding_creates_supplier(backend: _FakeBackend) -> None:
    extraction = SupplierDocExtraction(name="Acme Parts", contact_email="a@acme.com", phone="555-010-2938")
    deps = FoundationAgentDeps(extract_supplier=lambda img, mime: extraction)
    graph = get_compiled_foundation_graph(deps)

    state = graph.invoke(
        {
            "token": _token("fleet_manager"),
            "document_type": "supplier_doc",
            "image_bytes": b"jpeg",
            "mime_type": "image/jpeg",
        }
    )

    assert state["stage"] == "done"
    assert state["created_record"]["name"] == "Acme Parts"
    assert backend.create_supplier_calls == 1


def test_missing_jwt_halts_before_routing(backend: _FakeBackend) -> None:
    deps = FoundationAgentDeps()
    graph = get_compiled_foundation_graph(deps)

    state = graph.invoke({"token": None})

    assert state["stage"] == "halted"
    assert state.get("intent") is None
