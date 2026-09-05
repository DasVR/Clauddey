#!/usr/bin/env python3
"""SessionStart hook: tell the running Clauddey daemon a session began.

Never starts or stops the daemon — Clauddey runs as a persistent background
process (see host_bridge/install_startup.py), so this only pushes a status.
"""

import json
import sys

import _notify

_SOURCES = {
    "startup": "New session",
    "resume": "Resumed",
    "clear": "After clear",
    "compact": "After compaction",
}


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    source = hook_input.get("source") or ""
    label = _SOURCES.get(source, source[:21] if source else "Connected")
    _notify.notify("claude", "idle", label)
    sys.exit(0)


if __name__ == "__main__":
    main()
