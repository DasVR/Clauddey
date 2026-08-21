"""
Modular agent interfaces.

Real Claude (CLI log tail / SDK) and Cursor (extension / local API) adapters
should implement AgentInterface.parse_raw() and optionally poll(). The
boilerplate ships dummy parsers plus scripted demo events.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
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


class AgentInterface(ABC):
    name: str

    @abstractmethod
    def parse_raw(self, raw: dict[str, Any]) -> UnifiedEvent | None:
        """Translate a vendor-specific JSON blob into a UnifiedEvent."""

    def poll(self) -> UnifiedEvent | None:
        """Optional non-blocking poll (sockets, log tails). Default: idle."""
        return None


class CursorAgent(AgentInterface):
    """Cursor IDE Agent — replace parse_raw/poll with the local API or extension hook."""

    name = "cursor"

    def parse_raw(self, raw: dict[str, Any]) -> UnifiedEvent | None:
        provider = str(raw.get("provider") or raw.get("source") or "").lower()
        if provider and provider != "cursor":
            return None
        status = normalize_status(str(raw.get("status") or raw.get("state") or "idle"))
        msg = ascii_clip(str(raw.get("message") or raw.get("detail") or raw.get("msg") or ""))
        if not msg:
            msg = {
                "generating": "Generating code...",
                "thinking": "Thinking...",
                "waiting": "Waiting for approval",
                "done": "Task complete",
                "error": "Cursor error",
            }.get(status, "Cursor idle")
        return UnifiedEvent(agent="cursor", status=status, msg=msg, raw=raw)


class ClaudeAgent(AgentInterface):
    """Claude Code / Desktop — replace parse_raw/poll with CLI log or API callbacks."""

    name = "claude"

    def parse_raw(self, raw: dict[str, Any]) -> UnifiedEvent | None:
        provider = str(raw.get("provider") or raw.get("source") or "").lower()
        if provider and provider not in ("claude", "anthropic"):
            return None
        status = normalize_status(str(raw.get("status") or raw.get("state") or "idle"))
        msg = ascii_clip(str(raw.get("message") or raw.get("detail") or raw.get("msg") or ""))
        if not msg:
            msg = {
                "generating": "Claude writing...",
                "thinking": "Claude thinking...",
                "waiting": "Waiting for input",
                "done": "Claude finished",
                "error": "Claude error",
            }.get(status, "Claude idle")
        return UnifiedEvent(agent="claude", status=status, msg=msg, raw=raw)


def agent_for(name: str) -> AgentInterface:
    name = normalize_agent(name)
    if name == "cursor":
        return CursorAgent()
    if name == "claude":
        return ClaudeAgent()
    raise KeyError(f"unknown agent {name}")
