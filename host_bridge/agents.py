"""
Shared event type for the IPC and MCP ingestion paths.

Real per-program event sources live in ipc_server.py (anything that can reach
the bridge's socket/TCP endpoint — Claude Code hooks, shell scripts, etc.)
and, later, mcp_server.py (anything MCP-capable). Both construct a
UnifiedEvent directly via make_event() rather than going through a
per-vendor parser, since the wire shape for both surfaces is already
Clauddey's own {agent, status, msg}.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from protocol import ascii_clip, normalize_agent, normalize_status


@dataclass(frozen=True)
class UnifiedEvent:
    """Normalized event the aggregator and Flipper both understand."""

    agent: str
    status: str
    msg: str
    raw: dict[str, Any] = field(default_factory=dict)


def make_event(
    agent: str, status: str, msg: str = "", raw: dict[str, Any] | None = None
) -> UnifiedEvent:
    """Build a UnifiedEvent from a loosely-typed caller payload (IPC/MCP)."""
    return UnifiedEvent(
        agent=normalize_agent(agent),
        status=normalize_status(status),
        msg=ascii_clip(msg),
        raw=raw or {},
    )
