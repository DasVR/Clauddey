#!/usr/bin/env python3
"""UserPromptSubmit hook: show that Claude has started working on the new prompt."""

import sys

import _notify


def main() -> None:
    sys.stdin.read()  # drain the hook payload even though we don't need its fields
    _notify.notify("claude", "thinking", "Thinking...")
    sys.exit(0)


if __name__ == "__main__":
    main()
