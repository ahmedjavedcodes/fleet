"""LangGraph state schema for the Strategic Insights & Executive Dashboard Agent.

Mirrors ai_agents/specs/strategic-insights-agent.md's Behaviour section:

    Intent: executive_summary | cost_analysis | query

Unlike the other four agents, there is no document/image to structurally
signal intent from -- this agent is purely a read/synthesis layer, no
extraction skill at all. So classify_intent reads an explicit
`request_type` the caller sets directly, rather than inferring it from
image_bytes/document_type presence.

This agent is also the only one with a blanket, intent-independent RBAC
gate (checking_access, right after inject_context): FR 6 restricts ALL of
its tools to admin/fleet_manager, and two of the three tools it calls are
owned by other agents (get_fuel_trends_tool, get_maintenance_logs_tool)
with their own, broader role sets -- relying on those alone would let a
mechanic through on cost_analysis. See graph.py.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

Intent = Literal["executive_summary", "cost_analysis", "query"]
RequestType = Literal["executive_summary", "cost_analysis"]
QueryEntity = Literal["dashboard_summary", "fuel_trends", "fleet_health"]

Stage = Literal[
    "routing",
    "checking_access",
    "fetching_summary_data",
    "fetching_cost_data",
    "synthesizing",
    "querying",
    "done",
    "halted",
]


class InsightsAgentState(TypedDict, total=False):
    # caller context -- token is the raw JWT; the rest are populated by
    # inject_context() from it and re-derived into an AgentContext by any
    # node that needs to call a tool.
    token: str | None
    user_id: str | None
    organization_id: str | None
    role: str | None

    # routing input/output
    request_type: RequestType | None
    intent: Intent | None
    stage: Stage

    # shared optional filter
    month: str | None

    # executive_summary intermediate results
    dashboard_summary: dict[str, Any] | None
    fuel_trends: Any | None
    fleet_health: dict[str, Any] | None

    # cost_analysis intermediate results
    cost_correlation: list[dict[str, Any]] | None

    # query input/output
    query_entity: QueryEntity | None
    query_result: Any | None

    # terminal
    halt_reason: str | None
