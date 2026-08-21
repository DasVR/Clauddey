#!/usr/bin/env python3
"""
Clauddey Host Bridge — dummy multi-agent router.

Examples:
  python bridge.py --dry-run --demo
  python bridge.py --port /dev/ttyACM1 --demo
  python bridge.py --port auto

The demo ingests a mock Cursor event and a mock Claude event, aggregates them
into unified JSON, and writes that JSON to the serial transport. Incoming
Flipper commands are routed to the active agent's keymap.
"""

from __future__ import annotations

import argparse
import sys
import time

from agents import ClaudeAgent, CursorAgent, UnifiedEvent
from aggregator import Aggregator
from protocol import parse_command
from router import CommandRouter, os_dictation_hint
from serial_link import SerialTransport, StdoutTransport, Transport

DEMO_CURSOR_RAW = {
    "provider": "cursor",
    "event": "composer.state",
    "status": "generating",
    "message": "Generating code...",
}

DEMO_CURSOR_WAITING = {
    "provider": "cursor",
    "event": "composer.state",
    "status": "waiting_for_input",
    "message": "Accept the diff?",
}

DEMO_CLAUDE_RAW = {
    "provider": "claude",
    "event": "cli.session",
    "status": "thinking",
    "message": "Thinking...",
}

DEMO_CLAUDE_WAIT = {
    "provider": "claude",
    "event": "cli.session",
    "status": "waiting_for_input",
    "message": "Waiting for approval",
}


def push_event(agg: Aggregator, transport: Transport, event: UnifiedEvent | None) -> None:
    state = agg.ingest(event)
    if state is None:
        return
    line = state.as_line()
    print(f"[bridge] active={state.agent} status={state.status} msg={state.msg!r}")
    transport.send_line(line)


def run_demo(agg: Aggregator, transport: Transport, pause: float) -> None:
    cursor = CursorAgent()
    claude = ClaudeAgent()

    print("[demo] parsing mock Cursor event:", DEMO_CURSOR_RAW)
    push_event(agg, transport, cursor.parse_raw(DEMO_CURSOR_RAW))
    time.sleep(pause)

    print("[demo] parsing mock Cursor approval event:", DEMO_CURSOR_WAITING)
    push_event(agg, transport, cursor.parse_raw(DEMO_CURSOR_WAITING))
    time.sleep(pause)

    print("[demo] parsing mock Claude event:", DEMO_CLAUDE_RAW)
    push_event(agg, transport, claude.parse_raw(DEMO_CLAUDE_RAW))
    time.sleep(pause)

    print("[demo] parsing mock Claude wait event:", DEMO_CLAUDE_WAIT)
    push_event(agg, transport, claude.parse_raw(DEMO_CLAUDE_WAIT))
    print("[demo] Flipper OLED should now show CLAUDE / Waiting for approval")
    print("[demo]", os_dictation_hint())


def open_transport(port: str, baud: int, dry_run: bool) -> Transport:
    if dry_run or port in ("none", "dry", "stdout"):
        print("[bridge] dry-run serial (no device)")
        return StdoutTransport()

    print("[bridge] USB serial will auto-reconnect if the Flipper is undocked")
    return SerialTransport(port, baud=baud)


def pump(agg: Aggregator, router: CommandRouter, transport: Transport) -> None:
    """Non-blocking main loop: drain Flipper RX, then sleep briefly."""
    print("[bridge] listening for Flipper commands (Ctrl+C to quit)")
    try:
        while True:
            line = transport.try_recv_line(timeout=0.1)
            if line:
                cmd = parse_command(line)
                if cmd is None:
                    print(f"[bridge] ignore rx: {line.strip()!r}")
                    continue
                router.handle(cmd, active_agent=agg.state.agent)
    except KeyboardInterrupt:
        print("\n[bridge] stopping")
    finally:
        transport.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Clauddey host bridge")
    p.add_argument("--port", default="auto", help="Serial device, 'auto', or 'none'")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--dry-run", action="store_true", help="Print JSON instead of opening USB")
    p.add_argument("--demo", action="store_true", help="Inject mock Cursor + Claude events")
    p.add_argument("--demo-pause", type=float, default=0.8, help="Seconds between demo events")
    p.add_argument("--listen", action="store_true", help="Keep running after --demo")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    agg = Aggregator()
    router = CommandRouter()
    transport = open_transport(args.port, args.baud, args.dry_run)

    if args.demo:
        run_demo(agg, transport, pause=args.demo_pause)
        if not args.listen and args.dry_run:
            transport.close()
            return 0

    pump(agg, router, transport)
    return 0


if __name__ == "__main__":
    sys.exit(main())
