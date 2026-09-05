#!/usr/bin/env python3
"""SessionEnd hook: clear this agent's status on the Flipper.

Never stops the daemon — it keeps running for other sessions/programs.
"""

import json
import sys

import _notify

_REASONS = {
    "clear": "Cleared",
    "resume": "Switched session",
    "logout": "Logged out",
    "prompt_input_exit": "User exited",
    "bypass_permissions_disabled": "Bypass perms off",
    "other": "Disconnected",
}


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    raw_reason = hook_input.get("reason") or ""
    label = _REASONS.get(raw_reason, (raw_reason or "Disconnected"))[:21]
    _notify.notify("claude", "idle", label)
    sys.exit(0)


if __name__ == "__main__":
    main()
