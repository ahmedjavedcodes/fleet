"""MCP server exposing read-only fleet data access to LLM clients.

Binds the LLM to PostgreSQL for querying historical fleet records, parts
inventory, and shift logs (CLAUDE.md: Model Context Protocol). Every query
this server executes is first inspected by
`ai_agents.tools.safety_hooks.pre_tool_call` to guarantee read-only access.

NOTE: this local package is named `mcp` to match the directory layout in
CLAUDE.md, which shadows the installed `mcp` SDK package whenever
`ai_agents/` sits on `sys.path` (as it does for tests, via `pythonpath`).
Revisit packaging (e.g. an `ai_agents` src-layout, or renaming this SDK
import) before wiring this server up for real.
"""

from __future__ import annotations

from mcp.server import Server
from mcp.types import TextContent, Tool

from tools.safety_hooks import UnsafeSQLError, pre_tool_call

server = Server("fleet-postgres")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="query_fleet_data",
            description="Run a read-only SQL query against historical fleet records.",
            inputSchema={
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "query_fleet_data":
        raise ValueError(f"Unknown tool: {name}")

    try:
        safe_sql = pre_tool_call(arguments["sql"])
    except UnsafeSQLError as exc:
        return [TextContent(type="text", text=f"Rejected: {exc}")]

    # Execution wired up once the read-only SQLAlchemy session is available.
    return [TextContent(type="text", text=f"Would execute (read-only): {safe_sql}")]
