#!/usr/bin/env python3
"""Stop hook: Claude finished responding for this turn."""

import sys

import _notify


def main() -> None:
    sys.stdin.read()  # drain the hook payload even though we don't need its fields
    _notify.notify("claude", "done", "Done")
    sys.exit(0)


if __name__ == "__main__":
    main()
