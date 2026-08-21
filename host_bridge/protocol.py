"""Clauddey v1 newline-delimited JSON protocol (host side)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 1
MAX_MSG_LEN = 40
CDC_PACKET_SIZE = 64
LINE_MAX = 160

AGENTS = ("none", "cursor", "claude")
STATUSES = ("idle", "thinking", "generating", "waiting", "done", "error")
COMMANDS = ("ok", "cancel", "left", "right", "up", "down", "dictate")

_STATUS_ALIASES = {
    "coding": "generating",
    "waiting_for_input": "waiting",
    "approval": "waiting",
    "complete": "done",
    "success": "done",
    "fail": "error",
    "failed": "error",
}

_AGENT_ALIASES = {
    "cur": "cursor",
    "cld": "claude",
}


def normalize_agent(value: str | None) -> str:
    raw = (value or "none").strip().lower()
    return _AGENT_ALIASES.get(raw, raw if raw in AGENTS else "none")


def normalize_status(value: str | None) -> str:
    raw = (value or "idle").strip().lower()
    raw = _STATUS_ALIASES.get(raw, raw)
    return raw if raw in STATUSES else "idle"


def ascii_clip(text: str | None, limit: int = MAX_MSG_LEN) -> str:
    """OLED-safe: 7-bit ASCII, clipped. Flipper canvas cannot render UTF-8 glyphs."""
    cleaned = []
    for ch in text or "":
        o = ord(ch)
        cleaned.append(ch if 32 <= o < 127 else "?")
        if len(cleaned) >= limit:
            break
    return "".join(cleaned)


def pack_status(agent: str, status: str, msg: str = "") -> str:
    payload = {
        "v": PROTOCOL_VERSION,
        "agent": normalize_agent(agent),
        "status": normalize_status(status),
        "msg": ascii_clip(msg),
    }
    return json.dumps(payload, separators=(",", ":")) + "\n"


@dataclass(frozen=True)
class FlipperCommand:
    cmd: str
    agent: str
    mode: str

    @property
    def is_interactive(self) -> bool:
        return self.mode == "interactive"


def parse_command(line: str) -> FlipperCommand | None:
    text = (line or "").strip()
    if not text:
        return None
    try:
        data: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError:
        return None
    cmd = str(data.get("cmd", "")).strip().lower()
    if cmd not in COMMANDS:
        return None
    return FlipperCommand(
        cmd=cmd,
        agent=normalize_agent(str(data.get("agent", "none"))),
        mode=str(data.get("mode", "")).strip().lower(),
    )


class LineAssembler:
    """Hold a partial newline-delimited frame across 64-byte USB CDC packets."""

    def __init__(self, max_len: int = LINE_MAX) -> None:
        self.max_len = max_len
        self._buf = bytearray()
        self._drop = False

    def reset(self) -> None:
        self._buf.clear()
        self._drop = False

    def feed(self, chunk: bytes) -> list[str]:
        lines: list[str] = []
        for byte in chunk:
            if byte == 13:  # '\r'
                continue
            if byte == 10:  # '\n'
                if self._drop:
                    self.reset()
                    continue
                if self._buf:
                    lines.append(self._buf.decode("ascii", errors="replace"))
                self.reset()
                continue
            if self._drop:
                continue
            if len(self._buf) + 1 >= self.max_len:
                self._drop = True
                self._buf.clear()
                continue
            self._buf.append(byte)
        return lines
