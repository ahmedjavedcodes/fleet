"""Smart defaults and single-turn slot filling: obvious values are filled in, the rest is asked for once, and the
user's answer goes straight back into the tool call."""

from datetime import date, datetime, timedelta, timezone

import jwt
from langchain_core.messages import AIMessage

from agents.assignment.graph import AssignmentAgentDeps, get_compiled_assignment_graph
from agents.fuel.graph import FuelAgentDeps, get_compiled_fuel_graph
from agents.maintenance.graph import MaintenanceAgentDeps, get_compiled_maintenance_graph
from orchestrator.graph import OrchestratorDeps
from orchestrator.required_fields import missing_fields, needs_input_observation, not_run_observation
from orchestrator.runner import RunResult
from orchestrator.session import OrchestratorSession
from tools.schemas import WorkOrderExtraction


def _token(role: str = "admin") -> str:
    return jwt.encode({"sub": "u", "org": "o", "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}, "k", algorithm="HS256")


class _Capture:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, context, data):
        self.calls.append(data.model_dump(mode="json"))
        return {"id": "rec-1", **self.calls[-1]}


# --- maintenance: the odometer comes from the vehicle ----------------------------------------------------


def _maintenance(odometer, vehicle_odometer):
    capture = _Capture()
    deps = MaintenanceAgentDeps(
        extract_work_order=lambda img, mime, text=None: WorkOrderExtraction(
            issue_description="Brake service and filters", service_types=["brake_service", "filter_replacement"],
            service_scale="major", vehicle_plate="CD-5678", odometer=odometer, cost=35000,
        ),
        get_vehicles=lambda ctx: [{"id": "v2", "plate_number": "CD-5678", "current_odometer": vehicle_odometer}],
        get_drivers=lambda ctx: [],
        get_inventory=lambda ctx: [],
        create_maintenance_log=lambda ctx, data: capture(ctx, data),
        create_mechanic_report=lambda ctx, log_id, data: {"id": "r1"},
    )
    state = get_compiled_maintenance_graph(deps).invoke({"token": _token("mechanic"), "document_type": "work_order", "document_text": "brake service and filters, Rs 35000"})
    return state, capture


def test_a_work_order_without_an_odometer_uses_the_vehicles_last_reading() -> None:
    state, capture = _maintenance(odometer=None, vehicle_odometer=44200)

    assert state["stage"] == "done", state.get("halt_reason")
    assert capture.calls[0]["odometer_at_service"] == 44200
    assert "last recorded reading used" in capture.calls[0]["description"]
    assert capture.calls[0]["date"] == date.today().isoformat()


def test_a_stated_odometer_is_never_replaced_by_the_default() -> None:
    state, capture = _maintenance(odometer=45000, vehicle_odometer=44200)

    assert state["stage"] == "done" and capture.calls[0]["odometer_at_service"] == 45000
    assert "last recorded reading" not in (capture.calls[0]["description"] or "")


def test_a_vehicle_with_no_reading_at_all_still_has_to_be_asked() -> None:
    state, capture = _maintenance(odometer=None, vehicle_odometer=0)

    assert state["stage"] == "halted" and "odometer" in state["halt_reason"].lower() and capture.calls == []


# --- fuel: date today, odometer from the vehicle -----------------------------------------------------------


def _fuel(fields):
    capture = _Capture()
    deps = FuelAgentDeps(get_vehicles=lambda ctx: [{"id": "v1", "plate_number": "AB-1234", "current_odometer": 1000}], create_fuel_log=capture)
    return get_compiled_fuel_graph(deps).invoke({"token": _token(), "fuel_fields": fields}), capture


def test_a_typed_fuel_log_with_no_date_or_odometer_gets_today_and_the_last_reading() -> None:
    state, capture = _fuel({"vehicle_id": "v1", "liters_filled": 50, "total_cost": 14000})

    assert state["stage"] == "done", state.get("halt_reason")
    log = capture.calls[0]
    assert (log["date"], log["odometer_reading"]) == (date.today().isoformat(), 1000)
    assert "last recorded reading used" in log["notes"]


def test_a_typed_fuel_log_keeps_what_the_user_stated() -> None:
    state, capture = _fuel({"vehicle_id": "v1", "liters_filled": 50, "total_cost": 14000, "odometer_reading": 1500, "date": "2026-09-30", "notes": "night fill"})

    assert state["stage"] == "done"
    assert (capture.calls[0]["date"], capture.calls[0]["odometer_reading"], capture.calls[0]["notes"]) == ("2026-09-30", 1500, "night fill")


def test_the_fuel_figures_themselves_are_never_defaulted() -> None:
    state, capture = _fuel({"vehicle_id": "v1", "liters_filled": 50})

    assert state["stage"] == "halted" and capture.calls == []


# --- assignment: odometer from the vehicle, condition good ----------------------------------------------


def test_an_assignment_without_odometer_or_condition_takes_the_vehicles_reading_and_good() -> None:
    created = _Capture()
    deps = AssignmentAgentDeps(
        get_vehicles=lambda ctx: [{"id": "v1", "plate_number": "AB-1234", "current_odometer": 7300}],
        get_drivers=lambda ctx: [{"id": "d1", "full_name": "Omar Farooq"}],
        get_vehicle_history=lambda ctx, vid: [],
        get_driver_history=lambda ctx, did: {"driver_id": did, "current_assignment": None, "total_vehicles_driven": 0, "history": []},
        create_assignment=lambda ctx, vid, data: created(ctx, data),
    )
    request = {"vehicle_plate": "AB-1234", "driver_name": "Omar Farooq", "assigned_at": "2026-09-30T08:00:00"}

    state = get_compiled_assignment_graph(deps).invoke({"token": _token(), "assign_request": request})

    assert state["stage"] == "done", state.get("halt_reason")
    assert (created.calls[0]["start_odometer"], created.calls[0]["take_condition"]) == (7300, "good")


# --- what the orchestrator still asks for, and how -------------------------------------------------------


def test_only_what_cannot_be_inferred_is_asked_and_all_of_it_at_once() -> None:
    assert missing_fields("fuel", {"fuel_fields": {"liters_filled": 50}}, has_image=False) == ["the vehicle (plate number)", "the price per liter", "the total cost"]
    assert missing_fields("fuel", {"fuel_fields": {"vehicle_id": "v1", "liters_filled": 50, "total_cost": 14000}}, has_image=False) == []
    assert missing_fields("assignment", {"terminate_request": {"vehicle_plate": "AB-1234"}}, has_image=False) == []


def test_the_model_is_told_to_ask_once_and_to_merge_the_answer_into_the_same_call() -> None:
    for text in (not_run_observation("fuel", ["the total cost"]), needs_input_observation("maintenance", "Could not determine the odometer.")):
        assert "ONE short message" in text and "same tool again at once" in text


# --- two turns through a real session ---------------------------------------------------------------------


class _LLM:
    def __init__(self, *responses):
        self.responses, self.seen = list(responses), []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages, **kwargs):
        self.seen.append(messages)
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


class _Runner:
    def __init__(self, *results):
        self.calls, self.results = [], list(results)

    def run(self, agent, state, *, thread_id=None):
        self.calls.append((agent, state))
        return self.results.pop(0)


def _call(args):
    return AIMessage(content="", tool_calls=[{"name": "maintenance", "args": args, "id": "c1", "type": "tool_call"}])


def test_the_answer_to_a_missing_slot_runs_the_tool_in_that_same_turn_and_reaches_approval() -> None:
    halted = RunResult(status="halted", state={"halt_reason": "Could not determine the work order's odometer reading."}, thread_id="t1")
    pending = RunResult(status="awaiting_approval", state={"maintenance_log": {}, "extracted": {"vehicle_plate": "CD-5678", "odometer": 45000}}, thread_id="t2", pending_node="creating_log")
    note = "Major service for CD-5678: brake service and filters, Rs 35000"
    llm = _LLM(
        _call({"document_type": "work_order", "document_text": note}),
        AIMessage(content="Need the odometer."),  # planning, after the halt observation
        AIMessage(content="What is CD-5678's odometer reading?"),  # the reply
        _call({"document_type": "work_order", "document_text": f"{note}. Odometer 45000"}),
    )
    runner = _Runner(halted, pending)
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner))

    first = session.run("Log a major maintenance service for CD-5678. Brake service and filters for Rs 35,000.")
    second = session.run("odometer 45000")

    assert first.hitl_state is None and "odometer" in first.final_response.lower()
    assert [agent for agent, _ in runner.calls] == ["maintenance", "maintenance"]
    assert "45000" in runner.calls[1][1]["document_text"] and "brake service" in runner.calls[1][1]["document_text"].lower()
    assert second.hitl_state is not None and second.hitl_state["agent_name"] == "maintenance"  # the approval card, same turn
    assert len(llm.seen) == 4  # turn 2 is one planning call straight to the tool: no confirmation round


# --- the note survives the model dropping parts of it (found in the live run) ---------------------------------


def test_the_plate_the_user_named_is_added_when_the_model_left_it_out_of_the_note() -> None:
    from orchestrator.required_fields import merge_typed_note

    args = {"document_type": "work_order", "document_text": "major service, brake service and filters, Rs 35000"}
    out = merge_typed_note("maintenance", args, user_message="Log a major service for CD-5678. Brake service.", pending={})

    assert out["document_text"].endswith("Vehicle CD-5678") and out["document_text"].startswith("major service")
    assert merge_typed_note("maintenance", {**args, "document_text": "service on CD-5678"}, user_message="for CD-5678", pending={})["document_text"] == "service on CD-5678"


def test_an_answer_fragment_is_put_behind_the_held_back_note_and_never_duplicated() -> None:
    from orchestrator.required_fields import merge_typed_note

    held = {"maintenance": "Major service for CD-5678: brake service and filters, Rs 35000"}
    out = merge_typed_note("maintenance", {"document_type": "work_order", "document_text": "odometer 45000"}, user_message="odometer 45000", pending=held)
    assert out["document_text"] == f"{held['maintenance']}. odometer 45000"

    again = merge_typed_note("maintenance", {"document_type": "work_order", "document_text": out["document_text"]}, user_message="odometer 45000", pending=held)
    assert again["document_text"] == out["document_text"]

    bare = merge_typed_note("maintenance", {"document_type": "work_order"}, user_message="odometer 45000", pending=held)
    assert bare["document_text"] == f"{held['maintenance']}. odometer 45000"
    assert merge_typed_note("fuel", {"fuel_fields": {}}, user_message="x", pending=held) == {"fuel_fields": {}}


def test_a_part_that_is_not_in_stock_does_not_block_the_service() -> None:
    capture = _Capture()
    deps = MaintenanceAgentDeps(
        extract_work_order=lambda img, mime, text=None: WorkOrderExtraction(
            issue_description="Brake service", service_types=["brake_service"], vehicle_plate="CD-5678", odometer=45000,
            parts_used=[{"name_or_sku": "filters", "qty": None}],
        ),
        get_vehicles=lambda ctx: [{"id": "v2", "plate_number": "CD-5678", "current_odometer": 44000}],
        get_drivers=lambda ctx: [], get_inventory=lambda ctx: [],
        create_maintenance_log=lambda ctx, data: capture(ctx, data), create_mechanic_report=lambda ctx, log_id, data: {"id": "r1"},
    )

    state = get_compiled_maintenance_graph(deps).invoke({"token": _token("mechanic"), "document_type": "work_order", "document_text": "brake service and filters"})

    assert state["stage"] == "done", state.get("halt_reason")
    assert "none deducted: filters" in capture.calls[0]["description"]


def test_the_held_back_note_carries_over_even_if_the_model_forgets_it() -> None:
    halted = RunResult(status="halted", state={"halt_reason": "Could not determine the work order's odometer reading."}, thread_id="t1")
    pending = RunResult(status="awaiting_approval", state={"extracted": {}}, thread_id="t2", pending_node="creating_log")
    llm = _LLM(
        _call({"document_type": "work_order", "document_text": "brake service and filters Rs 35000"}),  # no plate: added from the message
        AIMessage(content="plan"), AIMessage(content="What is the odometer?"),
        _call({"document_type": "work_order", "document_text": "odometer 45000"}),  # the bare fragment
    )
    runner = _Runner(halted, pending)
    session = OrchestratorSession(_token(), deps=OrchestratorDeps(llm=llm, runner=runner))

    session.run("Log a major service for CD-5678, brake service and filters Rs 35000")
    second = session.run("odometer 45000")

    first_note, second_note = (call[1]["document_text"] for call in runner.calls)
    assert "CD-5678" in first_note
    assert "brake service and filters" in second_note and "odometer 45000" in second_note and "CD-5678" in second_note
    assert second.hitl_state is not None


def test_a_bare_follow_up_call_with_no_document_type_is_still_the_work_order() -> None:
    from orchestrator.required_fields import merge_typed_note

    held = {"maintenance": "Major service for ABC-234: brake service, Rs 35000"}
    out = merge_typed_note("maintenance", {"document_text": "odometer 45000, ABC-234"}, user_message="odometer 45000", pending=held)

    assert out["document_type"] == "work_order" and out["document_text"].startswith(held["maintenance"])
    assert merge_typed_note("maintenance", {"query_entity": "service_due"}, user_message="x", pending=held) == {"query_entity": "service_due"}
    assert merge_typed_note("maintenance", {}, user_message="x", pending={}) == {}
    assert merge_typed_note("accountability", {"document_text": "hit a pole"}, user_message="x", pending={})["document_type"] == "incident_report"
