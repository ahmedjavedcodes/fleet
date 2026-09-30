"""End-to-end tests for the Driver Accountability Agent's LangGraph
orchestration.

Each test is named after the Acceptance Criterion it covers in
ai_agents/specs/driver-accountability-agent.md, adjusted where the spec's
own AC 4 assumed RBAC the real backend doesn't have: driver CAN read their
own incidents (row-filtered server-side), it isn't refused outright -- see
mcp_server/accountability_tools.py's docstring for the corrected roles.
Only extraction is faked (no live Groq call); RBAC gating, entity
resolution, and backend calls all run through the real
mcp_server.accountability_tools / foundation_tools / fuel_tools code, with
call_backend swapped for an in-memory fake backend.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from agents.accountability.graph import AccountabilityAgentDeps, get_compiled_accountability_graph
from mcp_server import accountability_tools as at
from mcp_server import foundation_tools as vft
from mcp_server import fuel_tools as ft
from tools.api_client import BackendAPIError
from tools.file_parsers import ExtractionFailedError
from tools.schemas import IncidentExtraction


def _token(role: str, org: str = "org-1", sub: str = "user-1") -> str:
    payload = {"sub": sub, "org": org, "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, "irrelevant-signing-key", algorithm="HS256")


class _FakeBackend:
    def __init__(self) -> None:
        self.vehicles: list[dict] = []
        self.drivers: list[dict] = []
        self.incidents: list[dict] = []
        self.trips: list[dict] = []
        self.timelines: dict[str, list[dict]] = {}
        self.create_incident_calls = 0

    def __call__(self, method, path, *, token=None, json=None, params=None, timeout=10.0):
        if method == "GET" and path == "/api/v1/vehicles":
            return list(self.vehicles)
        if method == "GET" and path == "/api/v1/drivers":
            return list(self.drivers)
        if method == "GET" and path == "/api/v1/trips":
            return list(self.trips)
        if method == "GET" and path == "/api/v1/incidents":
            return list(self.incidents)

        if method == "POST" and path == "/api/v1/incidents":
            self.create_incident_calls += 1
            record = {"id": f"i{self.create_incident_calls}", **json}
            self.incidents.append(record)
            return record

        if method == "GET" and path.startswith("/api/v1/drivers/") and path.endswith("/timeline"):
            driver_id = path.split("/")[4]
            if driver_id not in self.timelines:
                raise BackendAPIError(403, "Cannot view another driver's timeline")
            return self.timelines[driver_id]

        raise AssertionError(f"unexpected backend call: {method} {path}")


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> _FakeBackend:
    fake = _FakeBackend()
    monkeypatch.setattr(at, "call_backend", fake)
    monkeypatch.setattr(vft, "call_backend", fake)
    monkeypatch.setattr(ft, "call_backend", fake)
    return fake


def _deps(backend: _FakeBackend, **overrides) -> AccountabilityAgentDeps:
    return AccountabilityAgentDeps(
        get_vehicles=vft.get_vehicles_tool,
        get_drivers=vft.get_drivers_tool,
        get_trip_logs=ft.get_trip_logs_tool,
        get_incidents=at.get_incidents_tool,
        get_driver_timeline=at.get_driver_timeline_tool,
        create_incident=at.create_incident_tool,
        **overrides,
    )


def test_ac1_clear_report_creates_incident(backend: _FakeBackend) -> None:
    backend.vehicles = [{"id": "v1", "plate_number": "ABC-123"}]
    backend.drivers = [{"id": "d1", "user_id": "someone-else", "full_name": "Jane Doe"}]
    extraction = IncidentExtraction(
        incident_date="2026-01-05", location="Main St", severity="moderate", incident_type="damage",
        vehicle_plate="abc 123", driver_name="Jane Doe", damage_description="Rear bumper dent",
    )
    deps = _deps(backend, extract_incident=lambda img, mime, text=None: extraction)
    graph = get_compiled_accountability_graph(deps)

    state = graph.invoke(
        {"token": _token("admin"), "document_type": "incident_report", "image_bytes": b"jpeg", "mime_type": "image/jpeg"}
    )

    assert state["stage"] == "done"
    assert state["created_record"]["vehicle_id"] == "v1"
    assert state["created_record"]["driver_id"] == "d1"
    assert state["created_record"]["severity"] == "moderate"
    assert backend.create_incident_calls == 1


def test_ac2_unreadable_report_halts(backend: _FakeBackend) -> None:
    def failing_extractor(img, mime, text=None):
        raise ExtractionFailedError("could not read the incident report")

    deps = _deps(backend, extract_incident=failing_extractor)
    graph = get_compiled_accountability_graph(deps)

    state = graph.invoke(
        {"token": _token("admin"), "document_type": "incident_report", "image_bytes": b"blurry", "mime_type": "image/jpeg"}
    )

    assert state["stage"] == "halted"
    assert backend.create_incident_calls == 0


def test_ac3_unmapped_plate_halts(backend: _FakeBackend) -> None:
    backend.vehicles = [{"id": "v1", "plate_number": "ABC-123"}]
    extraction = IncidentExtraction(
        severity="minor", incident_type="damage", vehicle_plate="ZZZ-999", damage_description="Scratch",
    )
    deps = _deps(backend, extract_incident=lambda img, mime, text=None: extraction)
    graph = get_compiled_accountability_graph(deps)

    state = graph.invoke(
        {"token": _token("admin"), "document_type": "incident_report", "image_bytes": b"jpeg", "mime_type": "image/jpeg"}
    )

    assert state["stage"] == "halted"
    assert "no vehicle" in state["halt_reason"].lower()
    assert backend.create_incident_calls == 0


def test_ac4_mechanic_refused_on_incident_tools(backend: _FakeBackend) -> None:
    deps = _deps(backend)
    graph = get_compiled_accountability_graph(deps)

    state = graph.invoke({"token": _token("mechanic"), "query_entity": "incidents"})

    assert state["stage"] == "halted"
    assert "permit" in state["halt_reason"].lower()


def test_ac4_corrected_driver_can_read_own_incidents_but_not_others_timeline(backend: _FakeBackend) -> None:
    backend.incidents = [{"id": "i1", "driver_id": "d1"}]
    backend.timelines = {"d1": [{"record_type": "incident", "summary": {"severity": "minor"}}]}
    deps = _deps(backend)
    graph = get_compiled_accountability_graph(deps)

    own_incidents = graph.invoke({"token": _token("driver"), "query_entity": "incidents"})
    assert own_incidents["stage"] == "done"

    other_driver_timeline = graph.invoke(
        {"token": _token("driver"), "query_entity": "driver_safety", "query_driver_id": "someone-elses-driver-id"}
    )
    assert other_driver_timeline["stage"] == "halted"


def test_ac5_admin_and_fleet_manager_query_incidents_and_driver_safety(backend: _FakeBackend) -> None:
    backend.incidents = [{"id": "i1"}]
    backend.timelines = {"d1": [{"record_type": "incident", "summary": {"severity": "severe"}}]}
    deps = _deps(backend)
    graph = get_compiled_accountability_graph(deps)

    for role in ["admin", "fleet_manager"]:
        incidents_state = graph.invoke({"token": _token(role), "query_entity": "incidents"})
        safety_state = graph.invoke({"token": _token(role), "query_entity": "driver_safety", "query_driver_id": "d1"})

        assert incidents_state["query_result"] == backend.incidents
        assert safety_state["query_result"] == {"incident_count": 1, "by_severity": {"severe": 1}}


def test_driver_filing_incident_forces_own_driver_id(backend: _FakeBackend) -> None:
    backend.vehicles = [{"id": "v1", "plate_number": "ABC-123"}]
    backend.drivers = [
        {"id": "d-caller", "user_id": "driver-self-id", "full_name": "Caller Driver"},
        {"id": "d-other", "user_id": "someone-else", "full_name": "Someone Else"},
    ]
    extraction = IncidentExtraction(
        severity="minor", incident_type="damage", vehicle_plate="ABC-123", driver_name="Someone Else",
        damage_description="Scratch",
    )
    deps = _deps(backend, extract_incident=lambda img, mime, text=None: extraction)
    graph = get_compiled_accountability_graph(deps)

    state = graph.invoke(
        {
            "token": _token("driver", sub="driver-self-id"),
            "document_type": "incident_report",
            "image_bytes": b"jpeg",
            "mime_type": "image/jpeg",
        }
    )

    assert state["stage"] == "done"
    assert state["created_record"]["driver_id"] == "d-caller"


def test_trip_audit_flags_off_hours_trips(backend: _FakeBackend) -> None:
    backend.trips = [
        {"id": "t1", "driver_id": "d1", "start_time": "2026-01-01T09:00:00", "end_time": "2026-01-01T10:00:00"},
        {"id": "t2", "driver_id": "d1", "start_time": "2026-01-01T02:00:00", "end_time": "2026-01-01T03:00:00"},
    ]
    deps = _deps(backend)
    graph = get_compiled_accountability_graph(deps)

    state = graph.invoke({"token": _token("fleet_manager"), "audit_target": {"driver_id": "d1"}})

    assert state["stage"] == "done"
    assert [t["id"] for t in state["audit_result"]] == ["t2"]


# --- explicit severity / attachment_url from the orchestrator's tool call ----------


def _incident(backend: _FakeBackend, extraction: IncidentExtraction, **tool_args):
    backend.vehicles = [{"id": "v1", "plate_number": "ABC-123"}]
    deps = _deps(backend, extract_incident=lambda img, mime, text=None: extraction)
    return get_compiled_accountability_graph(deps).invoke(
        {"token": _token("admin"), "document_type": "incident_report", "document_text": "typed account", **tool_args}
    )


def test_explicit_severity_overrides_extraction_and_fills_a_gap(backend: _FakeBackend) -> None:
    unread = IncidentExtraction(vehicle_plate="ABC-123", damage_description="Side swipe")
    assert _incident(backend, unread, severity="severe")["created_record"]["severity"] == "severe"

    misread = IncidentExtraction(vehicle_plate="ABC-123", damage_description="Side swipe", severity="minor")
    assert _incident(backend, misread, severity="critical")["created_record"]["severity"] == "critical"


@pytest.mark.parametrize(
    ("said", "filed"),
    [("High", "severe"), ("serious", "severe"), ("low", "minor"), ("Medium", "moderate"), ("fatal", "critical")],
)
def test_common_severity_words_map_onto_the_four_levels(backend: _FakeBackend, said: str, filed: str) -> None:
    extraction = IncidentExtraction(vehicle_plate="ABC-123", damage_description="Dent", severity=said)
    assert _incident(backend, extraction)["created_record"]["severity"] == filed


def test_unrecognised_severity_halts_instead_of_guessing(backend: _FakeBackend) -> None:
    state = _incident(backend, IncidentExtraction(vehicle_plate="ABC-123", damage_description="Dent", severity="meh"))
    assert state["stage"] == "halted"
    assert "minor, moderate, severe or critical" in state["halt_reason"]
    assert backend.create_incident_calls == 0


def test_explicit_attachment_url_is_filed_and_unsafe_ones_are_dropped(backend: _FakeBackend) -> None:
    extraction = IncidentExtraction(vehicle_plate="ABC-123", damage_description="Dent", severity="minor")
    filed = _incident(backend, extraction, attachment_url="/uploads/incidents/abc.jpg")
    assert filed["created_record"]["attachment_url"] == "/uploads/incidents/abc.jpg"

    from_text = extraction.model_copy(update={"attachment_url": "javascript:alert(1)"})
    assert _incident(backend, from_text)["created_record"]["attachment_url"] is None
