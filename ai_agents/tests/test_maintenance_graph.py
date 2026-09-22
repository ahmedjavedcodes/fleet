"""End-to-end tests for the Maintenance & Parts Inventory Agent's LangGraph
orchestration.

Each test is named after the Acceptance Criterion it covers in
ai_agents/specs/maintenance-inventory-agent.md. Only extraction is faked
(no live Groq call); RBAC gating, the stock-check guardrail, field
bridging, and backend calls all run through the real
mcp_server.maintenance_tools / mcp_server.foundation_tools code, with
call_backend swapped for an in-memory fake backend -- same pattern as
test_fuel_graph.py.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from agents.maintenance.graph import MaintenanceAgentDeps, get_compiled_maintenance_graph
from mcp_server import foundation_tools as vft
from mcp_server import maintenance_tools as mt
from tools.api_client import BackendAPIError
from tools.file_parsers import ExtractionFailedError
from tools.schemas import PartLineItem, PartsInvoiceExtraction, WorkOrderExtraction, InvoiceLineItem


def _token(role: str, org: str = "org-1", sub: str = "user-1") -> str:
    payload = {"sub": sub, "org": org, "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, "irrelevant-signing-key", algorithm="HS256")


class _FakeBackend:
    """In-memory stand-in for call_backend, shared by maintenance_tools and foundation_tools."""

    def __init__(self) -> None:
        self.vehicles: list[dict] = []
        self.inventory: list[dict] = []
        self.maintenance_logs: list[dict] = []
        self.reports: list[dict] = []
        self.create_log_calls = 0
        self.create_report_calls = 0
        self.update_inventory_calls = 0
        self.force_400_on_report = False

    def __call__(self, method, path, *, token=None, json=None, params=None, timeout=10.0):
        if method == "GET" and path == "/api/v1/vehicles":
            return list(self.vehicles)
        if method == "GET" and path == "/api/v1/inventory":
            return list(self.inventory)
        if method == "GET" and path == "/api/v1/inventory/low-stock":
            return [p for p in self.inventory if p["qty_on_hand"] <= p.get("reorder_threshold", 0)]
        if method == "GET" and path == "/api/v1/maintenance":
            return list(self.maintenance_logs)

        if method == "POST" and path == "/api/v1/maintenance":
            self.create_log_calls += 1
            record = {"id": f"log-{self.create_log_calls}", **json}
            self.maintenance_logs.append(record)
            return record

        if method == "POST" and path.startswith("/api/v1/maintenance/") and path.endswith("/mechanic-report"):
            self.create_report_calls += 1
            if self.force_400_on_report:
                raise BackendAPIError(400, "Insufficient stock")
            log_id = path.split("/")[4]
            record = {"id": "report-1", "maintenance_log_id": log_id, **json}
            self.reports.append(record)
            # apply the decrement like the real backend does
            for item in json.get("parts_used", []):
                part = next(p for p in self.inventory if p["id"] == item["part_id"])
                part["qty_on_hand"] -= item["qty"]
            return record

        if method == "PUT" and path.startswith("/api/v1/inventory/"):
            self.update_inventory_calls += 1
            part_id = path.split("/")[-1]
            part = next(p for p in self.inventory if p["id"] == part_id)
            part.update(json)
            return dict(part)

        raise AssertionError(f"unexpected backend call: {method} {path}")


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> _FakeBackend:
    fake = _FakeBackend()
    monkeypatch.setattr(mt, "call_backend", fake)
    monkeypatch.setattr(vft, "call_backend", fake)
    return fake


def _deps(backend: _FakeBackend, **overrides) -> MaintenanceAgentDeps:
    return MaintenanceAgentDeps(
        get_vehicles=vft.get_vehicles_tool,
        get_inventory=mt.get_inventory_tool,
        get_low_stock=mt.get_low_stock_tool,
        get_maintenance_logs=mt.get_maintenance_logs_tool,
        create_maintenance_log=mt.create_maintenance_log_tool,
        create_mechanic_report=mt.create_mechanic_report_tool,
        update_inventory=mt.update_inventory_tool,
        **overrides,
    )


def test_ac1_valid_work_order_creates_log_and_report(backend: _FakeBackend) -> None:
    backend.vehicles = [{"id": "v1", "plate_number": "ABC-123", "current_odometer": 9000}]
    backend.inventory = [{"id": "p1", "part_number": "BP-1", "name": "Brake Pad", "qty_on_hand": 10, "reorder_threshold": 2}]
    extraction = WorkOrderExtraction(
        issue_description="Brake noise", service_type="brake_service",
        parts_used=[PartLineItem(name_or_sku="BP-1", qty=2)], labor_hours=1.0, cost=80.0,
        vehicle_plate="abc 123", odometer=9500,
    )
    deps = _deps(backend, extract_work_order=lambda img, mime, text=None: extraction)
    graph = get_compiled_maintenance_graph(deps)

    state = graph.invoke({"token": _token("admin"), "document_type": "work_order", "image_bytes": b"jpeg", "mime_type": "image/jpeg"})

    assert state["stage"] == "done"
    assert state["maintenance_log"]["vehicle_id"] == "v1"
    assert state["mechanic_report"]["parts_used"][0]["part_id"] == "p1"
    assert backend.create_log_calls == 1
    assert backend.create_report_calls == 1


def test_ac2_insufficient_stock_halts_before_report(backend: _FakeBackend) -> None:
    backend.vehicles = [{"id": "v1", "plate_number": "ABC-123", "current_odometer": 9000}]
    backend.inventory = [{"id": "p1", "part_number": "BP-1", "name": "Brake Pad", "qty_on_hand": 1, "reorder_threshold": 2}]
    extraction = WorkOrderExtraction(
        issue_description="Brake noise", parts_used=[PartLineItem(name_or_sku="BP-1", qty=5)],
        vehicle_plate="ABC-123", odometer=9500,
    )
    deps = _deps(backend, extract_work_order=lambda img, mime, text=None: extraction)
    graph = get_compiled_maintenance_graph(deps)

    state = graph.invoke({"token": _token("mechanic"), "document_type": "work_order", "image_bytes": b"jpeg", "mime_type": "image/jpeg"})

    assert state["stage"] == "halted"
    assert "insufficient" in state["halt_reason"].lower()
    assert backend.create_log_calls == 1  # log itself was created
    assert backend.create_report_calls == 0


def test_ac3_backend_400_race_halts_without_retry(backend: _FakeBackend) -> None:
    backend.vehicles = [{"id": "v1", "plate_number": "ABC-123", "current_odometer": 9000}]
    backend.inventory = [{"id": "p1", "part_number": "BP-1", "name": "Brake Pad", "qty_on_hand": 10, "reorder_threshold": 2}]
    backend.force_400_on_report = True
    extraction = WorkOrderExtraction(
        issue_description="Brake noise", parts_used=[PartLineItem(name_or_sku="BP-1", qty=2)],
        vehicle_plate="ABC-123", odometer=9500,
    )
    deps = _deps(backend, extract_work_order=lambda img, mime, text=None: extraction)
    graph = get_compiled_maintenance_graph(deps)

    state = graph.invoke({"token": _token("admin"), "document_type": "work_order", "image_bytes": b"jpeg", "mime_type": "image/jpeg"})

    assert state["stage"] == "halted"
    assert "insufficient-stock conflict" in state["halt_reason"]
    assert "already created" in state["halt_reason"]
    assert backend.create_report_calls == 1  # no retry


def test_ac4_invoice_restocks_inventory(backend: _FakeBackend) -> None:
    backend.inventory = [{"id": "p1", "part_number": "OF-1", "name": "Oil Filter", "qty_on_hand": 5, "reorder_threshold": 2}]
    extraction = PartsInvoiceExtraction(line_items=[InvoiceLineItem(part_number="OF-1", qty_received=10, unit_cost=3.5)])
    deps = _deps(backend, extract_parts_invoice=lambda img, mime, text=None: extraction)
    graph = get_compiled_maintenance_graph(deps)

    state = graph.invoke({"token": _token("fleet_manager"), "document_type": "parts_invoice", "image_bytes": b"jpeg", "mime_type": "image/jpeg"})

    assert state["stage"] == "done"
    assert state["updated_parts"][0]["qty_on_hand"] == 15
    assert backend.update_inventory_calls == 1


def test_ac5_driver_refused_on_query_and_onboarding(backend: _FakeBackend) -> None:
    deps = _deps(backend)
    graph = get_compiled_maintenance_graph(deps)

    query_state = graph.invoke({"token": _token("driver"), "query_entity": "maintenance_logs"})
    assert query_state["stage"] == "halted"
    assert "permit" in query_state["halt_reason"].lower()

    extraction = WorkOrderExtraction(vehicle_plate="ABC-123", odometer=9500)
    deps2 = _deps(backend, extract_work_order=lambda img, mime, text=None: extraction)
    graph2 = get_compiled_maintenance_graph(deps2)
    onboard_state = graph2.invoke(
        {"token": _token("driver"), "document_type": "work_order", "image_bytes": b"jpeg", "mime_type": "image/jpeg"}
    )
    assert onboard_state["stage"] == "halted"
    assert backend.create_log_calls == 0


def test_ac6_fleet_manager_refused_on_writes_but_can_query(backend: _FakeBackend) -> None:
    backend.vehicles = [{"id": "v1", "plate_number": "ABC-123", "current_odometer": 9000}]
    extraction = WorkOrderExtraction(vehicle_plate="ABC-123", odometer=9500)
    deps = _deps(backend, extract_work_order=lambda img, mime, text=None: extraction)
    graph = get_compiled_maintenance_graph(deps)

    onboard_state = graph.invoke(
        {"token": _token("fleet_manager"), "document_type": "work_order", "image_bytes": b"jpeg", "mime_type": "image/jpeg"}
    )
    assert onboard_state["stage"] == "halted"
    assert backend.create_log_calls == 0

    query_state = graph.invoke({"token": _token("fleet_manager"), "query_entity": "maintenance_logs"})
    assert query_state["stage"] == "done"


def test_ac7_mechanic_refused_on_inventory_write_but_can_create_and_query(backend: _FakeBackend) -> None:
    backend.inventory = [{"id": "p1", "part_number": "OF-1", "name": "Oil Filter", "qty_on_hand": 5, "reorder_threshold": 2}]
    invoice = PartsInvoiceExtraction(line_items=[InvoiceLineItem(part_number="OF-1", qty_received=10, unit_cost=3.5)])
    deps = _deps(backend, extract_parts_invoice=lambda img, mime, text=None: invoice)
    graph = get_compiled_maintenance_graph(deps)

    restock_state = graph.invoke(
        {"token": _token("mechanic"), "document_type": "parts_invoice", "image_bytes": b"jpeg", "mime_type": "image/jpeg"}
    )
    assert restock_state["stage"] == "halted"
    assert backend.update_inventory_calls == 0

    query_state = graph.invoke({"token": _token("mechanic"), "query_entity": "inventory"})
    assert query_state["stage"] == "done"


@pytest.mark.parametrize("role", ["admin", "fleet_manager", "mechanic"])
def test_ac8_read_queries_return_results_for_permitted_roles(backend: _FakeBackend, role: str) -> None:
    backend.maintenance_logs = [{"id": "log1"}]
    backend.inventory = [{"id": "p1", "qty_on_hand": 5, "reorder_threshold": 2}]
    deps = _deps(backend)
    graph = get_compiled_maintenance_graph(deps)

    log_state = graph.invoke({"token": _token(role), "query_entity": "maintenance_logs"})
    inv_state = graph.invoke({"token": _token(role), "query_entity": "inventory"})

    assert log_state["query_result"] == backend.maintenance_logs
    assert inv_state["query_result"] == backend.inventory


def test_extraction_failure_halts_without_creating(backend: _FakeBackend) -> None:
    def failing_extractor(img, mime, text=None):
        raise ExtractionFailedError("could not read the work order")

    deps = _deps(backend, extract_work_order=failing_extractor)
    graph = get_compiled_maintenance_graph(deps)

    state = graph.invoke(
        {"token": _token("admin"), "document_type": "work_order", "image_bytes": b"blurry", "mime_type": "image/jpeg"}
    )

    assert state["stage"] == "halted"
    assert backend.create_log_calls == 0
