"""
Cross-platform IPC server: lets other processes (Claude Code hook scripts,
the MCP server, or anything else) push agent status into the running bridge.

Windows has no reliably-everywhere AF_UNIX story, so this mirrors the
sibling flipper-claude-buddy project's approach: on Windows, listen on a
fixed TCP port on 127.0.0.1 and drop a small marker file at the conventional
"socket path" containing `TCP:host:port`; elsewhere, open a real AF_UNIX
socket at that path. Either way, ipc_client.py's connect_ipc() figures out
which one it's talking to by looking at the path itself, not the platform.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
from collections.abc import Callable

from agents import make_event
from aggregator import Aggregator, AggregatedState

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

DEFAULT_SOCKET_PATH = os.environ.get(
    "CLAUDDEY_IPC_SOCKET", os.path.join(tempfile.gettempdir(), "clauddey-bridge.sock")
)
DEFAULT_TCP_HOST = "127.0.0.1"
DEFAULT_TCP_PORT = int(os.environ.get("CLAUDDEY_IPC_PORT", "51343"))


class IpcServer:
    """Accepts one JSON object per connection, dispatches it, replies with one JSON object."""

    def __init__(
        self,
        agg: Aggregator,
        on_status_change: Callable[[AggregatedState], None],
        socket_path: str = DEFAULT_SOCKET_PATH,
        tcp_host: str = DEFAULT_TCP_HOST,
        tcp_port: int = DEFAULT_TCP_PORT,
    ) -> None:
        self._agg = agg
        self._on_status_change = on_status_change
        self._socket_path = socket_path
        self._tcp_host = tcp_host
        self._tcp_port = tcp_port
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        if IS_WINDOWS:
            self._server = await asyncio.start_server(
                self._handle_client, host=self._tcp_host, port=self._tcp_port
            )
            with open(self._socket_path, "w", encoding="utf-8") as f:
                f.write(f"TCP:{self._tcp_host}:{self._tcp_port}")
            log.info(
                "IPC listening on %s:%s (marker %s)",
                self._tcp_host, self._tcp_port, self._socket_path,
            )
            return

        if os.path.exists(self._socket_path):
            os.unlink(self._socket_path)
        self._server = await asyncio.start_unix_server(
            self._handle_client, path=self._socket_path
        )
        os.chmod(self._socket_path, 0o666)
        log.info("IPC listening on %s", self._socket_path)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if os.path.exists(self._socket_path):
            try:
                os.unlink(self._socket_path)
            except OSError:
                pass

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            raw = await asyncio.wait_for(reader.read(65536), timeout=10)
            reply = self._dispatch(raw)
        except Exception as exc:
            reply = {"status": "error", "error": str(exc)}
        try:
            writer.write((json.dumps(reply) + "\n").encode("utf-8"))
            await writer.drain()
        finally:
            writer.close()

    def _dispatch(self, raw: bytes) -> dict:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"status": "error", "error": "invalid JSON"}

        action = payload.get("action")
        if action == "notify":
            event = make_event(
                agent=payload.get("agent", "none"),
                status=payload.get("status", "idle"),
                msg=payload.get("msg", ""),
            )
            state = self._agg.ingest(event)
            if state is not None:
                self._on_status_change(state)
            return {"status": "ok"}

        return {"status": "error", "error": f"unknown action {action!r}"}
