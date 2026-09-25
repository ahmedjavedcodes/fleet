"""Tests SubAgentRunner's pause/resume/modify mechanics against a real sub-agent
graph (Assignment) with fake backend-calling deps -- this exercises the actual
LangGraph interrupt_before + MemorySaver checkpointer behavior, not a mock of it.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from agents.assignment.graph import AssignmentAgentDeps
from orchestrator.registry import SUB_AGENT_REGISTRY
from orchestrator.runner import SubAgentRunner


def _token(role: str = "admin") -> str:
    payload = {"sub": "user-1", "org": "org-1", "role": role, "exp": datetime.now(timezone.utc) + timedelta(minutes=30)}
    return jwt.encode(payload, "irrelevant-signing-key", algorithm="HS256")


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> SubAgentRunner:
    vehicles = [{"id": "v1", "plate_number": "ABC-123"}]
    drivers = [{"id": "d1", "full_name": "Jane Doe"}]
    vehicle_history: dict = {}
    driver_history = {"d1": {"driver_id": "d1", "current_assignment": None, "total_vehicles_driven": 0, "history": []}}
    created = {}

    def create_assignment(context, vehicle_id, data):
        record = {"id": "a-new", "vehicle_id": vehicle_id, "released_at": None, **data.model_dump(mode="json")}
        created["record"] = record
        return record

    fake_deps = AssignmentAgentDeps(
        get_vehicles=lambda ctx: vehicles,
        get_drivers=lambda ctx: drivers,
        get_driver_history=lambda ctx, driver_id: driver_history.get(driver_id, {"current_assignment": None}),
        get_vehicle_history=lambda ctx, vehicle_id, target_date=None: vehicle_history.get(vehicle_id, []),
        create_assignment=create_assignment,
    )
    monkeypatch.setitem(
        SUB_AGENT_REGISTRY,
        "assignment",
        SUB_AGENT_REGISTRY["assignment"].__class__(
            name="assignment",
            build_graph=SUB_AGENT_REGISTRY["assignment"].build_graph,
            deps_factory=lambda: fake_deps,
            mutating_nodes=SUB_AGENT_REGISTRY["assignment"].mutating_nodes,
            description=SUB_AGENT_REGISTRY["assignment"].description,
        ),
    )
    runner = SubAgentRunner()
    runner._created = created  # test-only handle
    return runner


def test_run_pauses_before_mutating_node(runner: SubAgentRunner) -> None:
    result = runner.run(
        "assignment",
        {
            "token": _token(),
            "assign_request": {
                "vehicle_plate": "ABC-123", "driver_name": "Jane Doe", "assigned_at": "2026-01-01T08:00:00",
                "start_odometer": 1000, "take_condition": "good",
            },
        },
    )
    assert result.status == "awaiting_approval"
    assert result.pending_node == "executing"
    assert result.thread_id


def test_resume_approve_completes_the_write(runner: SubAgentRunner) -> None:
    paused = runner.run(
        "assignment",
        {
            "token": _token(),
            "assign_request": {
                "vehicle_plate": "ABC-123", "driver_name": "Jane Doe", "assigned_at": "2026-01-01T08:00:00",
                "start_odometer": 1000, "take_condition": "good",
            },
        },
    )
    result = runner.resume("assignment", paused.thread_id)
    assert result.status == "done"
    assert result.state["created_record"]["driver_id"] == "d1"


def test_resume_modify_changes_state_before_executing(runner: SubAgentRunner) -> None:
    paused = runner.run(
        "assignment",
        {
            "token": _token(),
            "assign_request": {
                "vehicle_plate": "ABC-123", "driver_name": "Jane Doe", "assigned_at": "2026-01-01T08:00:00",
                "start_odometer": 1000, "take_condition": "good",
            },
        },
    )
    # user edits the odometer reading during the HITL pause
    modified_request = {**paused.state["assign_request"], "start_odometer": 1500}
    result = runner.resume("assignment", paused.thread_id, updates={"assign_request": modified_request})
    assert result.status == "done"
    assert result.state["created_record"]["start_odometer"] == 1500


def test_insights_never_pauses(runner: SubAgentRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.insights.graph import InsightsAgentDeps

    monkeypatch.setitem(
        SUB_AGENT_REGISTRY,
        "insights",
        SUB_AGENT_REGISTRY["insights"].__class__(
            name="insights",
            build_graph=SUB_AGENT_REGISTRY["insights"].build_graph,
            deps_factory=lambda: InsightsAgentDeps(
                get_dashboard_summary=lambda ctx: {"total_vehicles": 5},
                get_fleet_health=lambda ctx: [],
                get_fuel_trends=lambda ctx: [],
                get_fuel_summary=lambda ctx, month=None: {"by_vehicle": []},
                get_maintenance_logs=lambda ctx: [],
            ),
            mutating_nodes=(),
            description=SUB_AGENT_REGISTRY["insights"].description,
        ),
    )
    result = runner.run("insights", {"token": _token(), "request_type": "executive_summary"})
    assert result.status == "done"
