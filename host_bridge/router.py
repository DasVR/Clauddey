"""
Context-aware command router.

Flipper only emits commands in Interactive mode; this module is a second gate
that refuses anything without mode=interactive, then dispatches by active agent.
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol

from protocol import FlipperCommand


class KeyBackend(Protocol):
    def tap(self, keys: str, reason: str) -> None: ...


class LogBackend:
    """Default backend: print the shortcut, never touch the real keyboard."""

    def __init__(self) -> None:
        self.history: list[tuple[str, str]] = []

    def tap(self, keys: str, reason: str) -> None:
        self.history.append((keys, reason))
        print(f"[router] {reason} -> keys: {keys}")


class DictationBackend(ABC):
    """Toggles the host's own speech-to-text. The Flipper has no microphone."""

    @abstractmethod
    def toggle(self, reason: str) -> None: ...


class NullDictationBackend(DictationBackend):
    """Default backend: log the request, never touch real dictation."""

    def __init__(self) -> None:
        self.history: list[str] = []

    def toggle(self, reason: str) -> None:
        self.history.append(reason)
        print(f"[router] {reason} -> dictation (no backend configured)")


@dataclass(frozen=True)
class Action:
    keys: str
    reason: str


# Placeholder chord map — swap for the bindings you actually use in Cursor / Claude.
CURSOR_MAP: dict[str, Action] = {
    "ok": Action("ctrl+enter", "cursor accept diff"),
    "cancel": Action("escape", "cursor reject / dismiss"),
    "right": Action("ctrl+enter", "cursor accept remaining"),
    "left": Action("escape", "cursor reject hunk"),
    "up": Action("alt+up", "cursor previous item"),
    "down": Action("alt+down", "cursor next item"),
}

CLAUDE_MAP: dict[str, Action] = {
    "ok": Action("enter", "claude approve / enter"),
    "cancel": Action("ctrl+c", "claude cancel"),
    "right": Action("alt+tab", "claude cycle terminal windows"),
    "left": Action("escape", "claude secondary cancel"),
    "up": Action("up", "claude previous"),
    "down": Action("down", "claude next"),
}

MAPS = {"cursor": CURSOR_MAP, "claude": CLAUDE_MAP}


class CommandRouter:
    def __init__(
        self,
        backend: KeyBackend | None = None,
        dictation: DictationBackend | None = None,
    ) -> None:
        self.backend = backend or LogBackend()
        self.dictation = dictation or NullDictationBackend()
        self.blocked: list[FlipperCommand] = []
        self.dispatched: list[tuple[str, Action]] = []

    def handle(self, command: FlipperCommand | None, active_agent: str) -> bool:
        if command is None:
            return False

        # Defense in depth: even if a buggy firmware sends a frame, drop it.
        if not command.is_interactive:
            self.blocked.append(command)
            print(
                f"[router] BLOCKED cmd={command.cmd} mode={command.mode!r} "
                "(Flipper must be in Interactive mode)"
            )
            return False

        agent = command.agent if command.agent in MAPS else active_agent

        # Dictation is host-side-only and isn't a keychord — route it to the
        # dedicated DictationBackend instead of the keystroke KeyBackend.
        if command.cmd == "dictate":
            self.dictation.toggle(f"{agent}/dictate")
            return True

        table = MAPS.get(agent)
        if not table:
            print(f"[router] no keymap for agent={agent!r}")
            return False

        action = table.get(command.cmd)
        if action is None:
            print(f"[router] unmapped cmd={command.cmd} agent={agent}")
            return False

        self.dispatched.append((agent, action))
        self.backend.tap(action.keys, f"{agent}/{command.cmd}: {action.reason}")
        return True


def default_backends() -> tuple[KeyBackend, DictationBackend]:
    """Real keystroke/dictation backends on Windows; log-only elsewhere."""
    if sys.platform == "win32":
        from input_win import Win32KeyBackend
        from voice_win import Win32DictationBackend

        return Win32KeyBackend(), Win32DictationBackend()
    return LogBackend(), NullDictationBackend()
