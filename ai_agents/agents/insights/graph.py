"""Strategic Insights & Executive Dashboard Agent orchestration (LangGraph).

Wires the router, the RBAC gate, and the MCP tools together per
ai_agents/specs/strategic-insights-agent.md's Behaviour section:

    inject_context -> checking_access -> classify_intent
        -> [executive_summary] fetching_summary_data -> synthesizing
        -> [cost_analysis] fetching_cost_data -> synthesizing
        -> [query] querying

Every dependency is injected via InsightsAgentDeps, same pattern as the
other four agents, so tests can substitute fakes without a live backend.
This agent never writes anything (FR: "Read-only agent").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from langgraph.graph import END, StateGraph

from agents.insights.state import InsightsAgentState
from agents.insights.synthesizer import correlate_costs, synthesize_fleet_health
from mcp_server.fuel_tools import get_fuel_trends_tool
from mcp_server.insights_tools import (
    PermissionDeniedError,
    get_dashboard_summary_tool,
    get_fleet_health_tool,
    get_fuel_summary_tool,
)
from mcp_server.maintenance_tools import get_maintenance_logs_tool
from tools.api_client import BackendAPIError
from tools.auth_context import AgentContext, InvalidTokenError, build_context

_INSIGHTS_ROLES = frozenset({"admin", "fleet_manager"})

Fetcher = Callable[..., Any]


@dataclass
class InsightsAgentDeps:
    """Injectable seams. Defaults are the real, backend-calling tools."""

    get_dashboard_summary: Fetcher = get_dashboard_summary_tool
    get_fleet_health: Fetcher = get_fleet_health_tool
    get_fuel_trends: Fetcher = get_fuel_trends_tool
    get_fuel_summary: Fetcher = get_fuel_summary_tool
    get_maintenance_logs: Fetcher = get_maintenance_logs_tool


def _context_from_state(state: InsightsAgentState) -> AgentContext:
    return AgentContext(
        token=state.get("token") or "",
        user_id=state.get("user_id") or "",
        organization_id=state.get("organization_id") or "",
        role=state.get("role") or "",
    )


def inject_context(state: InsightsAgentState) -> InsightsAgentState:
    try:
        context = build_context(state.get("token"))
    except InvalidTokenError as exc:
        return {**state, "stage": "halted", "halt_reason": str(exc)}
    return {
        **state,
        "user_id": context.user_id,
        "organization_id": context.organization_id,
        "role": context.role,
        "stage": "checking_access",
    }


def checking_access(state: InsightsAgentState) -> InsightsAgentState:
    """Blanket RBAC gate before any backend call -- FR 6 restricts every
    tool this agent uses to admin/fleet_manager, but two of the three
    tools it calls (get_fuel_trends_tool, get_maintenance_logs_tool) are
    owned by other agents with broader role sets of their own. Checking
    once here, rather than trusting each reused tool's own gate, is what
    makes the restriction actually blanket."""
    if state.get("role") not in _INSIGHTS_ROLES:
        return {
            **state,
            "stage": "halted",
            "halt_reason": f"Role '{state.get('role')}' is not permitted to access strategic insights; requires admin/fleet_manager.",
        }
    return {**state, "stage": "routing"}


def classify_intent(state: InsightsAgentState) -> InsightsAgentState:
    request_type = state.get("request_type")
    if request_type == "executive_summary":
        return {**state, "intent": "executive_summary", "stage": "fetching_summary_data"}
    if request_type == "cost_analysis":
        return {**state, "intent": "cost_analysis", "stage": "fetching_cost_data"}
    return {**state, "intent": "query", "stage": "querying"}


def _make_fetch_summary_node(deps: InsightsAgentDeps):
    def fetch(state: InsightsAgentState) -> InsightsAgentState:
        context = _context_from_state(state)
        try:
            summary = deps.get_dashboard_summary(context)
            trends = deps.get_fuel_trends(context)
            health = deps.get_fleet_health(context)
        except BackendAPIError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}

        return {**state, "dashboard_summary": summary, "fuel_trends": trends, "fleet_health": health, "stage": "synthesizing"}

    return fetch


def _make_fetch_cost_node(deps: InsightsAgentDeps):
    def fetch(state: InsightsAgentState) -> InsightsAgentState:
        context = _context_from_state(state)
        try:
            fuel_summary = deps.get_fuel_summary(context, state.get("month"))
            maintenance_logs = deps.get_maintenance_logs(context)
        except BackendAPIError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}

        correlation = correlate_costs(fuel_summary.get("by_vehicle") or [], maintenance_logs)
        return {**state, "cost_correlation": correlation, "stage": "done"}

    return fetch


def synthesize(state: InsightsAgentState) -> InsightsAgentState:
    fleet_health = synthesize_fleet_health(state.get("fleet_health") or [])
    return {**state, "fleet_health": fleet_health, "stage": "done"}


def _make_query_node(deps: InsightsAgentDeps):
    fetchers: dict[str, Fetcher] = {
        "dashboard_summary": deps.get_dashboard_summary,
        "fuel_trends": deps.get_fuel_trends,
        "fleet_health": deps.get_fleet_health,
    }

    def query(state: InsightsAgentState) -> InsightsAgentState:
        entity = state.get("query_entity")
        fetcher = fetchers.get(entity or "")
        if fetcher is None:
            return {**state, "stage": "halted", "halt_reason": f"Unsupported or missing query_entity: {entity!r}."}

        context = _context_from_state(state)
        try:
            result = fetcher(context)
        except BackendAPIError as exc:
            return {**state, "stage": "halted", "halt_reason": str(exc)}

        return {**state, "query_result": result, "stage": "done"}

    return query


def _route_after(state: InsightsAgentState) -> str:
    return "end" if state.get("stage") in ("halted", "done") else state["stage"]


def build_insights_graph(deps: InsightsAgentDeps | None = None) -> StateGraph:
    deps = deps or InsightsAgentDeps()
    graph = StateGraph(InsightsAgentState)

    graph.add_node("inject_context", inject_context)
    graph.add_node("checking_access", checking_access)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("fetching_summary_data", _make_fetch_summary_node(deps))
    graph.add_node("synthesizing", synthesize)
    graph.add_node("fetching_cost_data", _make_fetch_cost_node(deps))
    graph.add_node("querying", _make_query_node(deps))

    graph.set_entry_point("inject_context")
    graph.add_conditional_edges("inject_context", _route_after, {"end": END, "checking_access": "checking_access"})
    graph.add_conditional_edges("checking_access", _route_after, {"end": END, "routing": "classify_intent"})
    graph.add_conditional_edges(
        "classify_intent",
        _route_after,
        {
            "fetching_summary_data": "fetching_summary_data",
            "fetching_cost_data": "fetching_cost_data",
            "querying": "querying",
        },
    )
    graph.add_conditional_edges(
        "fetching_summary_data", _route_after, {"end": END, "synthesizing": "synthesizing"}
    )
    graph.add_edge("synthesizing", END)
    graph.add_edge("fetching_cost_data", END)
    graph.add_edge("querying", END)

    return graph


def get_compiled_insights_graph(deps: InsightsAgentDeps | None = None):
    return build_insights_graph(deps).compile()
