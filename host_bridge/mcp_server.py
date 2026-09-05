"""
MCP server exposing Clauddey's status surface over streamable HTTP, for any
MCP-capable client (Claude Desktop, Cursor, etc.) rather than just Claude
Code's own hooks. Shares the same Aggregator the IPC server and hooks use —
no duplicated status logic between the two surfaces.

Runs as "streamable HTTP" (not stdio): this is a long-running daemon serving
possibly-simultaneous clients, which is exactly the shape stdio MCP servers
(spawned 1:1 per client process) aren't built for.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from mcp.server.mcpserver import MCPServer

from agents import make_event
from aggregator import AggregatedState, Aggregator

log = logging.getLogger(__name__)


def build_mcp_server(
    agg: Aggregator, on_status_change: Callable[[AggregatedState], None]
) -> MCPServer:
    server = MCPServer(
        name="clauddey",
        instructions=(
            "Tools for showing this agent's status on a Clauddey-connected "
            "Flipper Zero. Call clauddey_notify whenever your status changes "
            "(starting a task, waiting for approval, done, error)."
        ),
    )

    @server.tool()
    async def clauddey_notify(agent: str, status: str, msg: str = "") -> str:
        """Push a status update to the Flipper.

        agent: a short name for the calling program, e.g. 'claude' or 'cursor'.
        status: one of 'idle', 'thinking', 'generating', 'waiting', 'done', 'error'.
        msg: a short (<=40 char) human-readable status line for the OLED.

        Must stay async: the MCP framework runs a *sync* tool function in a
        worker thread with no event loop, and on_status_change() schedules
        an asyncio task (writing to the transport) — that only works from
        the main event loop that async tools run on directly.
        """
        event = make_event(agent=agent, status=status, msg=msg)
        state = agg.ingest(event)
        if state is not None:
            on_status_change(state)
        return "ok"

    return server
