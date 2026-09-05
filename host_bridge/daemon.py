#!/usr/bin/env python3
"""
Clauddey persistent daemon.

Wraps bridge.py's connect/pump loop with a singleton guard and an optional
tray icon, so it can run headless in the background (launched once at login
by install_startup.py) instead of being started manually per session.
bridge.py's pump() already reconnects forever on its own; this just adds the
"only one instance" and "visible status" pieces on top.

Singleton uses a Win32 named mutex rather than a pidfile: a pidfile keyed on
a recorded PID number is racy on Windows, since PIDs are recycled quickly
enough that a stale file can point at some unrelated, currently-alive
process and permanently refuse to restart after a crash or force-kill. A
named mutex is released by the OS the instant the owning process exits, no
matter how it exits, so there's nothing to go stale.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import sys

from aggregator import Aggregator, AggregatedState
from bridge import build_parser, connect_with_retry, open_transport, pump
from ipc_server import IpcServer
from router import CommandRouter, default_backends
from transport import Transport

log = logging.getLogger(__name__)

_MUTEX_NAME = "Global\\ClauddeyBridgeSingleton"
_ERROR_ALREADY_EXISTS = 183

_mutex_handle: int | None = None


def acquire_singleton(mutex_name: str = _MUTEX_NAME) -> bool:
    """Return True if we now own the singleton mutex; False if another instance holds it."""
    global _mutex_handle
    if sys.platform != "win32":
        return True  # no cross-instance guard outside Windows for now

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, mutex_name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        log.error("Clauddey daemon already running")
        return False
    _mutex_handle = handle
    return True


def release_singleton() -> None:
    global _mutex_handle
    if _mutex_handle is not None:
        ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(_mutex_handle)
        _mutex_handle = None


async def _send_state(transport: Transport, state: AggregatedState) -> None:
    await transport.write(state.as_line().encode("ascii", errors="replace"))
    await transport.drain()


async def amain(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    agg = Aggregator()
    backend, dictation = default_backends()
    router = CommandRouter(backend=backend, dictation=dictation)
    transport = open_transport(args.port, args.baud, args.dry_run, args.transport)

    loop = asyncio.get_running_loop()
    quit_event = asyncio.Event()

    tray = None
    try:
        from tray import Tray

        tray = Tray(on_quit=lambda: loop.call_soon_threadsafe(quit_event.set))
        tray.start()
    except Exception as exc:
        log.warning("Tray icon unavailable (%s); running headless", exc)

    if tray:
        tray.set_status("connecting")
    await connect_with_retry(transport)
    if tray:
        tray.set_status("connected")

    def _on_status_change(state: AggregatedState) -> None:
        log.info("active=%s status=%s msg=%r", state.agent, state.status, state.msg)
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
        log.info("MCP server on http://127.0.0.1:%d/mcp", args.mcp_port)

    def _on_reconnect() -> None:
        if tray:
            tray.set_status("connected")

    pump_task = asyncio.create_task(pump(agg, router, transport, on_connect=_on_reconnect))
    quit_task = asyncio.create_task(quit_event.wait())
    await asyncio.wait({pump_task, quit_task}, return_when=asyncio.FIRST_COMPLETED)

    if not pump_task.done():
        pump_task.cancel()
    if ipc is not None:
        await ipc.stop()
    if mcp_task is not None:
        mcp_task.cancel()
    if tray:
        tray.stop()
    transport.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    if not acquire_singleton():
        return 1
    try:
        return asyncio.run(amain(argv))
    except KeyboardInterrupt:
        return 0
    finally:
        release_singleton()


if __name__ == "__main__":
    sys.exit(main())
