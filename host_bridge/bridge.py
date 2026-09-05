#!/usr/bin/env python3
"""
Clauddey Host Bridge — async multi-agent router.

Examples:
  python bridge.py --dry-run
  python bridge.py --port COM5       # Windows
  python bridge.py --port /dev/ttyACM1  # Linux
  python bridge.py --port auto

Real agent events arrive over the IPC socket (see ipc_server.py/ipc_client.py)
from Claude Code hooks or anything else that can reach it — not from any
scripted demo data. Incoming Flipper commands are routed to the active
agent's keymap via a real (or, off Windows, log-only) keystroke backend.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Callable

import config
from aggregator import Aggregator, AggregatedState
from ipc_server import DEFAULT_SOCKET_PATH, IpcServer
from protocol import parse_command
from router import CommandRouter, default_backends
from transport import StdoutTransport, Transport
from transport_auto import AutoTransport
from transport_bt import BtTransport
from transport_usb import UsbTransport

log = logging.getLogger(__name__)

RECONNECT_MIN_S = 0.5
RECONNECT_MAX_S = 5.0


def open_transport(port: str, baud: int, dry_run: bool, transport_kind: str) -> Transport:
    if dry_run or port in ("none", "dry", "stdout"):
        print("[bridge] dry-run serial (no device)")
        return StdoutTransport()

    if transport_kind == "usb":
        print("[bridge] USB serial will auto-reconnect if the Flipper is undocked")
        return UsbTransport(port, baud=baud)
    if transport_kind == "ble":
        print("[bridge] BLE will auto-reconnect if the Flipper is out of range")
        return BtTransport()

    print("[bridge] auto transport: USB first, BLE fallback")
    return AutoTransport(port, baud=baud)


async def connect_with_retry(transport: Transport) -> None:
    """Keep retrying transport.connect() with exponential backoff until it succeeds."""
    backoff = RECONNECT_MIN_S
    while not await transport.connect():
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2.0, RECONNECT_MAX_S)


async def pump(
    agg: Aggregator,
    router: CommandRouter,
    transport: Transport,
    on_connect: Callable[[], None] | None = None,
) -> None:
    """Main loop: reconnect on disconnect, replay last status, route Flipper RX.

    `on_connect`, if given, fires each time a (re)connect succeeds — the
    daemon uses it to update the tray icon's status.
    """
    print("[bridge] listening for Flipper commands (Ctrl+C to quit)")
    try:
        while True:
            if transport.is_closing:
                print("[bridge] disconnected; reconnecting...")
                await connect_with_retry(transport)
                print("[bridge] reconnected")
                if on_connect is not None:
                    on_connect()
                replay = agg.state.as_line()
                await transport.write(replay.encode("ascii", errors="replace"))
                await transport.drain()
                print("[bridge] replayed last status after reconnect")

            line = await transport.readline()
            if not line:
                continue
            cmd = parse_command(line.decode("ascii", errors="replace"))
            if cmd is None:
                print(f"[bridge] ignore rx: {line!r}")
                continue
            router.handle(cmd, active_agent=agg.state.agent)
    finally:
        transport.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Clauddey host bridge")
    p.add_argument("--port", default="auto", help="Serial device, 'auto', or 'none'")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument(
        "--transport",
        choices=("auto", "usb", "ble"),
        default=config.TRANSPORT,
        help="Link type: try USB then BLE (auto), USB only, or BLE only",
    )
    p.add_argument("--dry-run", action="store_true", help="Print JSON instead of opening a real link")
    p.add_argument(
        "--ipc-socket",
        default=DEFAULT_SOCKET_PATH,
        help="Path other processes use to push status (see ipc_client.py)",
    )
    p.add_argument("--no-ipc", action="store_true", help="Disable the IPC server")
    p.add_argument("--mcp-port", type=int, default=8787, help="Port for the MCP streamable-HTTP endpoint")
    p.add_argument("--no-mcp", action="store_true", help="Disable the MCP server")
    return p


async def amain(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    agg = Aggregator()
    backend, dictation = default_backends()
    router = CommandRouter(backend=backend, dictation=dictation)
    transport = open_transport(args.port, args.baud, args.dry_run, args.transport)

    await connect_with_retry(transport)

    def _on_status_change(state: AggregatedState) -> None:
        print(f"[bridge] active={state.agent} status={state.status} msg={state.msg!r}")
        asyncio.ensure_future(_send_state(transport, state))

    ipc: IpcServer | None = None
    if not args.no_ipc:
        ipc = IpcServer(agg, _on_status_change, socket_path=args.ipc_socket)
        await ipc.start()

    mcp_task: asyncio.Task | None = None
    if not args.no_mcp:
        from mcp_server import build_mcp_server

        mcp = build_mcp_server(agg, _on_status_change)
        mcp_task = asyncio.create_task(
            mcp.run_streamable_http_async(host="127.0.0.1", port=args.mcp_port)
        )
        print(f"[bridge] MCP server on http://127.0.0.1:{args.mcp_port}/mcp")

    try:
        await pump(agg, router, transport)
    finally:
        if ipc is not None:
            await ipc.stop()
        if mcp_task is not None:
            mcp_task.cancel()
    return 0


async def _send_state(transport: Transport, state: AggregatedState) -> None:
    await transport.write(state.as_line().encode("ascii", errors="replace"))
    await transport.drain()


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(amain(argv))
    except KeyboardInterrupt:
        print("\n[bridge] stopping")
        return 0


if __name__ == "__main__":
    sys.exit(main())
