"""Pick the active agent and emit a single Flipper status payload."""

from __future__ import annotations

from dataclasses import dataclass

from agents import UnifiedEvent
from protocol import pack_status


@dataclass
class AggregatedState:
    agent: str = "none"
    status: str = "idle"
    msg: str = ""

    def as_line(self) -> str:
        return pack_status(self.agent, self.status, self.msg)


class Aggregator:
    """
    Last non-idle event wins. Idle events only take over if the current agent
    itself went idle, so a background Cursor heartbeat cannot steal Claude's
    approval prompt.
    """

    def __init__(self) -> None:
        self.state = AggregatedState()

    def ingest(self, event: UnifiedEvent | None) -> AggregatedState | None:
        if event is None:
            return None

        current = self.state
        incoming_idle = event.status == "idle"
        current_idle = current.status == "idle" or current.agent == "none"

        if incoming_idle and not current_idle and event.agent != current.agent:
            return None

        changed = (
            event.agent != current.agent
            or event.status != current.status
            or event.msg != current.msg
        )
        self.state = AggregatedState(agent=event.agent, status=event.status, msg=event.msg)
        return self.state if changed else None
