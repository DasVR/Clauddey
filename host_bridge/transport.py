"""Async transport abstraction for the Clauddey host bridge.

`Transport` is the seam between protocol/framing logic (protocol.py) and the
physical link — USB CDC serial (transport_usb.py), BLE (a future
transport_bt.py), or this module's StdoutTransport stub for --dry-run.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod


class Transport(ABC):
    """A byte-line link to the Flipper. All I/O is asyncio-native."""

    @abstractmethod
    async def connect(self) -> bool:
        """Attempt to establish the link. Returns False if unavailable right now."""

    @abstractmethod
    async def readline(self) -> bytes:
        """Return the next complete line (with trailing newline), or b"" once closed."""

    @abstractmethod
    async def write(self, data: bytes) -> None:
        """Queue *data* for transmission."""

    @abstractmethod
    async def drain(self) -> None:
        """Wait until queued writes have been flushed to the link."""

    def close(self) -> None:
        """Best-effort, non-blocking teardown."""

    async def aclose(self) -> None:
        """Async teardown; default just calls close()."""
        self.close()

    @property
    @abstractmethod
    def is_closing(self) -> bool:
        """True once the underlying link has been torn down (or never connected)."""

    async def get_rssi(self) -> int | None:
        """Signal strength, for transports that have a concept of one (BLE)."""
        return None


class StdoutTransport(Transport):
    """Dry-run transport: print payloads instead of touching real hardware."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self._incoming: asyncio.Queue[bytes] = asyncio.Queue()
        self._closed = False

    async def connect(self) -> bool:
        self._closed = False
        return True

    async def readline(self) -> bytes:
        if self._closed:
            return b""
        return await self._incoming.get()

    def inject_rx(self, line: str) -> None:
        """Test/demo helper: queue a line as if it arrived from the Flipper."""
        text = line if line.endswith("\n") else line + "\n"
        self._incoming.put_nowait(text.encode("ascii", errors="replace"))

    async def write(self, data: bytes) -> None:
        text = data.decode("ascii", errors="replace")
        self.sent.append(text)
        print(f"[serial tx] {text.rstrip()}", flush=True)

    async def drain(self) -> None:
        return

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._incoming.put_nowait(b"")

    @property
    def is_closing(self) -> bool:
        return self._closed
