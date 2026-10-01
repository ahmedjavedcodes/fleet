"""Before any write: ask for what is missing, and show the approver exactly what will be written."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import jwt
import pytest
from langchain_core.messages import AIMessage

from agents.fuel.graph import _resolve_amounts, get_compiled_fuel_graph, sanitize
from orchestrator.approval_summary import summarize_pending
from orchestrator.graph import OrchestratorDeps
from orchestrator.required_fields import fill_defaults, missing_fields, needs_user_input
from orchestrator.runner import RunResult
from orchestrator.session import OrchestratorSession
from tools import file_parsers
from tools.schemas import FuelReceiptExtraction

FULL_FUEL = {"vehicle_id": "v1", "date": "2026-09-30", "odometer_reading": 46500, "liters_filled": 50, "price_per_liter": 280, "total_cost": 14000}
WORK_ORDER = "the work order or parts invoice details (a photo, or the text: vehicle plate, odometer, services, cost)"
INCIDENT = "a description of the incident (what happened, when, where, which vehicle)"


@pytest.mark.parametrize(
    ("agent", "args", "image", "expected"),
    [
        ("fuel", {"fuel_fields": {"vehicle_id": "v1", "liters_filled": 50}}, False, ["the date", "the exact odometer reading", "the price per liter", "the total cost", "the liters filled"][:0] or ["the date", "the exact odometer reading", "the price per liter", "the total cost"]),
        ("fuel", {"fuel_fields": FULL_FUEL}, False, []),
        ("fuel", {"fuel_fields": {k: v for k, v in FULL_FUEL.items() if k != "total_cost"}}, False, []),  # two of three give the third
        ("fuel", {"fuel_fields": {"vehicle_id": "v1"}}, True, []),  # the receipt photo supplies the rest
        ("fuel", {"query_entity": "fuel_logs"}, False, []),
        ("assignment", {"assign_request": {"vehicle_plate": "AB-1234"}}, False,
         ["the driver's name", "the odometer reading at the start", "the vehicle's condition when taken (good, fair or poor)"]),
        ("assignment", {"terminate_request": {"vehicle_plate": "AB-1234", "end_odometer": 5, "leave_condition": "good"}}, False, []),
        ("maintenance", {"document_type": "work_order"}, False, [WORK_ORDER]),
        ("maintenance", {"document_type": "work_order", "document_text": "oil change"}, False, []),
        ("maintenance", {"document_type": "work_order"}, True, []),
        ("accountability", {"document_type": "incident_report"}, False, [INCIDENT]),
        ("foundation", {"document_type": "license"}, False, ["a photo of the document"]),
    ],
)
def test_what_a_write_still_needs_from_the_user(agent, args, image, expected) -> None:
    assert sorted(missing_fields(agent, args, has_image=image)) == sorted(expected)


def test_an_assignment_without_a_time_is_taken_now() -> None:
    now = datetime(2026, 9, 30, 12, 0)
    out = fill_defaults("assignment", {"assign_request": {"vehicle_plate": "AB-1234"}}, now=now)
    assert out["assign_request"]["assigned_at"] == "2026-09-30T12:00:00"
    kept = fill_defaults("assignment", {"assign_request": {"assigned_at": "2026-01-01T08:00:00"}}, now=now)
    assert kept["assign_request"]["assigned_at"] == "2026-01-01T08:00:00"


@pytest.mark.parametrize("reason", ["Could not determine the work order's odometer reading.", "Invalid fuel_fields: 2 validation errors", "driver_history query requires query_driver_id."])
def test_a_halt_that_is_really_a_missing_answer_is_recognised(reason) -> None:
    assert needs_user_input(reason)


def test_a_refusal_is_not_a_missing_answer() -> None:
    assert not needs_user_input("Role 'driver' is not permitted to modify assignments.")


# --- through a real session --------------------------------------------------------------------


def _token() -> str:
    return jwt.encode({"sub": "u", "org": "o", "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}, "k", algorithm="HS256")


class _LLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.seen = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages, **kwargs):
        self.seen.append(messages)
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


class _Runner:
    def __init__(self, result=None):
        self.calls, self.result = [], result

    def run(self, agent, state, *, thread_id=None):
        self.calls.append((agent, state))
        return self.result


def _call(name, args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "c1", "type": "tool_call"}])


def _run(message, call, result=None):
    llm, runner = _LLM(call, AIMessage(content="ok")), _Runner(result)
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner))
    return session.run(message), runner, llm


def _last_prompt(llm) -> str:
    return "\n".join(str(m.content) for m in llm.seen[-1])


def test_an_incomplete_fuel_log_is_not_run_and_the_model_is_told_to_ask() -> None:
    result, runner, llm = _run("Log 50 liters of fuel for the Hilux", _call("fuel", {"fuel_fields": {"vehicle_id": "v1", "liters_filled": 50}}))

    assert runner.calls == []  # nothing ran, so no approval card with blanks
    assert result.status == "done" and result.hitl_state is None
    prompt = _last_prompt(llm)
    assert "NOT RUN" in prompt and "the exact odometer reading" in prompt and "the date" in prompt
    assert "ask the user" in prompt.lower()


def test_a_complete_fuel_log_reaches_the_sub_agent() -> None:
    done = RunResult(status="done", state={"created_record": {}}, thread_id="t")
    _, runner, _ = _run("Log this fuel", _call("fuel", {"fuel_fields": FULL_FUEL}), done)

    assert [agent for agent, _ in runner.calls] == ["fuel"]


def test_an_assignment_with_a_missing_driver_asks_instead_of_running() -> None:
    _, runner, llm = _run("Assign the Hilux AB-1234", _call("assignment", {"assign_request": {"vehicle_plate": "AB-1234"}}))

    assert runner.calls == [] and "the driver's name" in _last_prompt(llm)


def test_a_sub_agent_halt_for_a_missing_detail_becomes_a_question_for_the_user() -> None:
    halted = RunResult(status="halted", state={"halt_reason": "Could not determine the work order's odometer reading."}, thread_id="t")
    _, _, llm = _run("Log an oil change service on the vehicle AB-1234", _call("maintenance", {"document_type": "work_order", "document_text": "oil change AB-1234"}), halted)

    prompt = _last_prompt(llm)
    assert "needs more information from the user" in prompt and "odometer reading" in prompt


def test_the_reply_prompt_tells_the_model_to_ask_not_to_apologise() -> None:
    _, _, llm = _run("Log fuel", _call("fuel", {"fuel_fields": {"vehicle_id": "v1"}}))

    assert "ask the user for exactly those items" in _last_prompt(llm)


# --- the approval card's content ----------------------------------------------------------------


def _labels(rows):
    return {r["label"]: r["value"] for r in rows}


def test_a_fuel_approval_lists_every_figure() -> None:
    rows = _labels(summarize_pending("fuel", {
        "vehicle_plate": "AB-1234",
        "sanitized": {"vehicle_id": "x", "date": date(2026, 9, 24), "odometer_reading": 46500, "liters_filled": Decimal("39.2"),
                      "price_per_liter": Decimal("391.96"), "total_cost": Decimal("15365.00"), "fuel_station_name": "Mehar Petroleum Okara",
                      "notes": "Product: Hi-Super"},
    }))

    assert rows == {"Vehicle": "AB-1234", "Date": "2026-09-24", "Station": "Mehar Petroleum Okara", "Odometer": "46,500 km", "Liters": "39.2 L",
                    "Price per liter": "Rs 391.96", "Total cost": "Rs 15,365", "Notes": "Product: Hi-Super"}


def test_a_maintenance_approval_shows_vehicle_service_description_and_cost() -> None:
    rows = _labels(summarize_pending("maintenance", {"extracted": {
        "vehicle_plate": "CD-5678", "odometer": 82000, "service_types": ["brake_service", "oil_change"], "service_scale": "major",
        "issue_description": "Brake service & filter replacement", "cost": 35000.0, "parts_used": [{"name_or_sku": "Oil filter", "qty": 2}]}}))

    assert rows["Vehicle"] == "CD-5678" and rows["Service scale"] == "Major" and rows["Total cost"] == "Rs 35,000"
    assert rows["Description"] == "Brake service & filter replacement" and rows["Parts used"] == "Oil filter x2"
    assert rows["Service type"] == "brake service, oil change"


def test_incident_assignment_and_registry_approvals_are_described_too() -> None:
    incident = summarize_pending("accountability", {"severity": "severe", "extracted": {"vehicle_plate": "AB-1234", "damage_description": "Dented door"}})
    assert _labels(incident) == {"Vehicle": "AB-1234", "Severity": "Severe", "Description": "Dented door"}
    assign = {"intent": "assign_asset", "assign_request": {"vehicle_plate": "AB-1234", "driver_name": "Ali Khan", "start_odometer": 100, "take_condition": "good"}}
    assert _labels(summarize_pending("assignment", assign))["Driver"] == "Ali Khan"
    reg = _labels(summarize_pending("foundation", {"document_type": "vehicle_doc", "sanitized": {"plate_number": "EF-9012", "make": "Toyota", "vehicle_id": "hidden"}}))
    assert reg["Plate number"] == "EF-9012" and "Vehicle id" not in reg


def test_a_summary_never_breaks_the_approval() -> None:
    assert summarize_pending("fuel", {"sanitized": "garbage"}) == []
    assert summarize_pending("insights", {}) == []


def test_the_paused_session_carries_the_summary_to_the_card() -> None:
    paused = RunResult(status="awaiting_approval", state={"vehicle_plate": "AB-1234", "sanitized": {"liters_filled": 50, "total_cost": 14000}},
                       thread_id="t", pending_node="creating")
    result, _, _ = _run("Log this fuel", _call("fuel", {"fuel_fields": FULL_FUEL}), paused)

    assert result.status == "awaiting_approval"
    assert result.hitl_state["approval_prompt"] == "Record this fuel entry?"
    assert {"label": "Total cost", "value": "Rs 14,000"} in result.hitl_state["summary"]


# --- OCR ---------------------------------------------------------------------------------------


def test_the_receipt_prompt_names_each_field_with_its_exact_format(monkeypatch) -> None:
    seen = {}

    class _Chain:
        def with_structured_output(self, schema):
            return self

        def invoke(self, messages):
            seen["text"] = messages[0].content[0]["text"]
            return FuelReceiptExtraction()

    monkeypatch.setattr(file_parsers, "get_vision_model", lambda: _Chain())
    file_parsers.extract_fuel_receipt(b"x", "image/png")

    for needle in ("2026-09-24", "Hi-Super", "39.20", "391.96", "15365.00", "price_per_liter", "product", "station_name"):
        assert needle in seen["text"]


def test_the_printed_unit_price_and_product_are_used_over_derived_values() -> None:
    ext = FuelReceiptExtraction(station_name="Mehar Petroleum Okara", receipt_date=date(2026, 9, 24), product="Hi-Super",
                                liters=39.2, price_per_liter=391.96, total_cost=15365.0)
    assert _resolve_amounts({}, ext.model_dump()) == (Decimal("39.2"), Decimal("391.9600"), Decimal("15365.0"))

    rec = sanitize({"extracted": ext.model_dump(), "vehicle_id": "v1", "vehicle_plate": "AB-1234", "fuel_fields": {"odometer_reading": 46500}})["sanitized"]

    assert rec["price_per_liter"] == Decimal("391.9600") and rec["fuel_station_name"] == "Mehar Petroleum Okara"
    assert rec["notes"] == "Product: Hi-Super; Station: Mehar Petroleum Okara" and str(rec["date"]) == "2026-09-24"
    assert rec["liters_filled"] == Decimal("39.2") and rec["total_cost"] == Decimal("15365.0")


def test_a_misread_unit_price_is_ignored_when_it_disagrees_with_litres_times_price() -> None:
    assert _resolve_amounts({}, {"liters": 39.2, "price_per_liter": 3.9, "total_cost": 15365.0})[1] == Decimal("391.9643")


def test_a_typed_fuel_log_with_two_amounts_derives_the_third(monkeypatch) -> None:
    from tests.test_fuel_graph import _FakeBackend, _deps, _token as fuel_token
    from mcp_server import foundation_tools as vft, fuel_tools as ft

    fake = _FakeBackend()
    fake.vehicles = [{"id": "v1", "plate_number": "AB-1234", "current_odometer": 1000}]
    monkeypatch.setattr(ft, "call_backend", fake)
    monkeypatch.setattr(vft, "call_backend", fake)
    fields = {"vehicle_id": "v1", "date": "2026-09-30", "odometer_reading": 1500, "liters_filled": 50, "price_per_liter": 280}

    state = get_compiled_fuel_graph(_deps(fake)).invoke({"token": fuel_token("admin"), "fuel_fields": fields})

    assert state["stage"] == "done" and Decimal(state["created_record"]["total_cost"]) == Decimal("14000")
