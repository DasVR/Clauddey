#!/usr/bin/env python3
"""Notification hook: forwards relevant Claude Code notifications to Clauddey."""

import json
import sys

import _notify

_NOTIFY_MAP = {
    "idle_prompt": ("waiting", "Waiting for input"),
}


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    entry = _NOTIFY_MAP.get(hook_input.get("notification_type", ""))
    if entry is None:
        sys.exit(0)

    status, msg = entry
    _notify.notify("claude", status, msg)
    sys.exit(0)


if __name__ == "__main__":
    main()
