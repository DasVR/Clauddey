"""USB CDC transport — wraps serial_asyncio with Clauddey's dual-CDC port
discovery and 64-byte-packet line framing (extracted from serial_link.py)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator

import serial_asyncio

from protocol import CDC_PACKET_SIZE, LINE_MAX, LineAssembler
from transport import Transport

log = logging.getLogger(__name__)


def find_flipper_port() -> str | None:
    """Locate the Flipper's Clauddey CDC port.

    Dual-CDC exposes two ports per device (CLI on the lower-numbered one,
    Clauddey's app on the higher); picks the higher when both are present.
    """
    try:
        from serial.tools import list_ports
    except ImportError:
        return None

    hits: list[str] = []
    for info in list_ports.comports():
        blob = f"{info.description} {info.manufacturer} {info.product}".lower()
        if "flipper" in blob or "stm32" in blob or "stmicro" in blob:
            hits.append(info.device)
    if not hits:
        return None
    hits.sort()
    return hits[-1] if len(hits) > 1 else hits[0]


def chunk_cdc(data: bytes, size: int = CDC_PACKET_SIZE) -> Iterator[bytes]:
    """Split a payload into USB CDC bulk packets (typically 64 bytes)."""
    if not data:
        return
    for i in range(0, len(data), size):
        yield data[i : i + size]


class UsbTransport(Transport):
    """
    USB CDC transport that survives Flipper undock/redock.

    `port` may be a device path or `auto` (re-resolved on every connect(), since
    dual-CDC ACM/COM numbers often change after re-enumeration).
    """

    def __init__(self, port: str = "auto", baud: int = 115200) -> None:
        self._port_hint = port
        self._baud = baud
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._closed = True
        self._lines = LineAssembler(max_len=LINE_MAX)
        self._rx: asyncio.Queue[bytes] = asyncio.Queue()
        self._read_task: asyncio.Task | None = None

    def _resolve_port(self) -> str | None:
        if self._port_hint not in ("auto", "", None):
            return self._port_hint
        return find_flipper_port()

    async def connect(self) -> bool:
        port = self._resolve_port()
        if not port:
            log.warning("USB: no Flipper serial port found")
            return False
        try:
            self._reader, self._writer = await serial_asyncio.open_serial_connection(
                url=port, baudrate=self._baud
            )
        except Exception as exc:
            log.warning("USB: connect failed on %s: %s", port, exc)
            return False
        self._lines.reset()
        self._closed = False
        self._read_task = asyncio.create_task(self._read_loop())
        log.info("USB: connected on %s", port)
        return True

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while True:
                chunk = await self._reader.read(CDC_PACKET_SIZE)
                if not chunk:
                    break
                for line in self._lines.feed(chunk):
                    await self._rx.put((line + "\n").encode("ascii", errors="replace"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("USB: read error: %s", exc)
        finally:
            self._closed = True
            await self._rx.put(b"")

    async def readline(self) -> bytes:
        return await self._rx.get()

    async def write(self, data: bytes) -> None:
        if self._writer is None:
            return
        try:
            for packet in chunk_cdc(data):
                self._writer.write(packet)
        except Exception as exc:
            log.warning("USB: write error: %s", exc)
            self._closed = True

    async def drain(self) -> None:
        if self._writer is None:
            return
        try:
            await self._writer.drain()
        except Exception as exc:
            log.warning("USB: drain error: %s", exc)
            self._closed = True

    def close(self) -> None:
        if self._read_task is not None:
            self._read_task.cancel()
            self._read_task = None
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:
                pass
            self._writer = None
        self._reader = None
        self._closed = True

    @property
    def is_closing(self) -> bool:
        return self._closed
