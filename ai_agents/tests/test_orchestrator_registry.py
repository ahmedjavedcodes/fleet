"""Regression test for orchestrator/registry.py's mutating_nodes claims.

The spec only gave "e.g." examples of mutating node names (executing,
creating, restocking); the registry's per-agent lists were found by
grepping each graph.py's real add_node calls. This proves those names
actually exist as nodes in each agent's own graph -- if a future change to
any agents/*/graph.py renames a node, this fails loudly instead of the
orchestrator silently never triggering interrupt_before on it.
"""

from orchestrator.registry import SUB_AGENT_REGISTRY


def test_every_mutating_node_exists_in_its_graph() -> None:
    for name, spec in SUB_AGENT_REGISTRY.items():
        graph = spec.build_graph(spec.deps_factory())
        node_names = set(graph.nodes.keys())
        for node in spec.mutating_nodes:
            assert node in node_names, f"{name}: mutating node {node!r} not found in {sorted(node_names)}"


def test_insights_has_no_mutating_nodes() -> None:
    assert SUB_AGENT_REGISTRY["insights"].mutating_nodes == ()


def test_all_six_agents_registered() -> None:
    assert set(SUB_AGENT_REGISTRY) == {"foundation", "fuel", "maintenance", "accountability", "insights", "assignment"}
