"""LangGraph state schema for the Driver & Vehicle Assignment Agent.

Mirrors ai_agents/specs/assignment-agent.md's Behaviour section:

    Intent: assign_asset | terminate_assignment | query
    assign_asset sub-flow: ResolvingEntities -> ValidatingConflicts ->
    Executing -> Done | Halted(reason)

Like the Strategic Insights Agent, there is no document/image involved --
this is a structured-input agent. Intent is decided from which of
assign_request/terminate_request the caller populated, same structural
approach as every other agent's router, just keyed on request shape
instead of image presence.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

Intent = Literal["assign_asset", "terminate_assignment", "query"]
QueryEntity = Literal["driver_history", "vehicle_history"]

Stage = Literal[
    "routing",
    "resolving_entities",
    "validating_conflicts",
    "executing",
    "querying",
    "done",
    "halted",
]


class AssignmentAgentState(TypedDict, total=False):
    # caller context -- token is the raw JWT; the rest are populated by
    # inject_context() from it and re-derived into an AgentContext by any
    # node that needs to call a tool.
    token: str | None
    user_id: str | None
    organization_id: str | None
    role: str | None

    # routing input/output
    intent: Intent | None
    stage: Stage

    # assign_asset input: {vehicle_plate, driver_name, assigned_at,
    # start_odometer, take_condition, take_notes}
    assign_request: dict[str, Any] | None

    # terminate_assignment input: {vehicle_plate, released_at, end_odometer,
    # leave_condition, leave_notes}
    terminate_request: dict[str, Any] | None

    # intermediate resolution results
    vehicle_id: str | None
    driver_id: str | None
    created_record: dict[str, Any] | None

    # query input/output
    query_entity: QueryEntity | None
    query_driver_id: str | None
    query_vehicle_id: str | None
    query_target_date: str | None
    query_result: Any | None

    # terminal
    halt_reason: str | None
