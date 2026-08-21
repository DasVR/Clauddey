"""
Non-blocking USB serial transport with auto-reconnect.

A reader thread copies complete lines into a queue. The main loop never blocks
on Serial.read(). Writes are mutex-protected, split into 64-byte CDC packets,
and retried after the Flipper is undocked/re-enumerated.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any, Protocol

from protocol import CDC_PACKET_SIZE, LINE_MAX, LineAssembler

SerialOpener = Callable[[str, int], Any]
PortFinder = Callable[[], str | None]


class Transport(Protocol):
    def send_line(self, line: str) -> None: ...
    def try_recv_line(self, timeout: float = 0.0) -> str | None: ...
    def close(self) -> None: ...


class StdoutTransport:
    """Dry-run transport: print payloads that would go to the Flipper."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self._incoming: queue.Queue[str] = queue.Queue()

    def send_line(self, line: str) -> None:
        text = line if line.endswith("\n") else line + "\n"
        self.sent.append(text)
        print(f"[serial tx] {text.rstrip()}", flush=True)

    def inject_rx(self, line: str) -> None:
        self._incoming.put(line if line.endswith("\n") else line + "\n")

    def try_recv_line(self, timeout: float = 0.0) -> str | None:
        try:
            return self._incoming.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        return


def chunk_cdc(data: bytes, size: int = CDC_PACKET_SIZE) -> Iterator[bytes]:
    """Split a payload into USB CDC bulk packets (typically 64 bytes)."""
    if not data:
        return
    for i in range(0, len(data), size):
        yield data[i : i + size]


def _default_opener(port: str, baud: int) -> Any:
    try:
        import serial  # type: ignore
    except ImportError as exc:
        raise SystemExit("pyserial is required: pip install pyserial") from exc
    return serial.Serial(port=port, baudrate=baud, timeout=0.05, write_timeout=0.2)


class SerialTransport:
    """
    USB CDC transport that survives Flipper undock/redock.

    `port` may be a device path or `auto`. Each reconnect re-runs the port
    finder because dual-CDC ACM numbers often change after re-enumeration.
    The last status line is replayed so the OLED is not stuck on a stale frame.
    """

    def __init__(
        self,
        port: str,
        baud: int = 115200,
        reconnect_s: float = 0.5,
        opener: SerialOpener | None = None,
        port_finder: PortFinder | None = None,
    ) -> None:
        self._port_hint = port
        self._baud = baud
        self._reconnect_s = reconnect_s
        self._opener = opener or _default_opener
        self._port_finder = port_finder or find_flipper_port
        self._serial: Any | None = None
        self._rx: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._lines = LineAssembler(max_len=LINE_MAX)
        self._last_tx: str | None = None
        self._thread = threading.Thread(target=self._io_loop, name="clauddey-cdc", daemon=True)
        self._thread.start()
        print(f"[serial] waiting for Flipper ({port} @ {baud})", flush=True)

    def _resolve_port(self) -> str | None:
        if self._port_hint not in ("auto", "", None):
            return self._port_hint
        return self._port_finder()

    def _close_unlocked(self) -> None:
        ser = self._serial
        self._serial = None
        self._lines.reset()
        if ser is None:
            return
        try:
            ser.close()
        except Exception:
            pass

    def _write_unlocked(self, data: bytes) -> bool:
        ser = self._serial
        if ser is None:
            return False
        try:
            for packet in chunk_cdc(data):
                ser.write(packet)
            ser.flush()
            return True
        except Exception as exc:
            print(f"[serial] write error: {exc}", file=sys.stderr, flush=True)
            self._close_unlocked()
            return False

    def _connect(self) -> bool:
        port = self._resolve_port()
        if not port:
            return False
        try:
            ser = self._opener(port, self._baud)
        except Exception as exc:
            print(f"[serial] open {port} failed: {exc}", file=sys.stderr, flush=True)
            return False
        with self._lock:
            self._serial = ser
            replay = self._last_tx
            wrote = True
            if replay:
                wrote = self._write_unlocked(replay.encode("ascii", errors="replace"))
        print(f"[serial] connected {port}", flush=True)
        if replay and wrote:
            print("[serial] replayed last status after connect", flush=True)
        return True

    def _io_loop(self) -> None:
        backoff = self._reconnect_s
        while not self._stop.is_set():
            with self._lock:
                ser = self._serial
            if ser is None:
                if not self._connect():
                    time.sleep(backoff)
                    backoff = min(backoff * 2.0, 5.0)
                    continue
                backoff = self._reconnect_s
                continue

            try:
                chunk = ser.read(CDC_PACKET_SIZE)
            except Exception as exc:
                print(f"[serial] disconnected: {exc}", file=sys.stderr, flush=True)
                with self._lock:
                    if self._serial is ser:
                        self._close_unlocked()
                time.sleep(self._reconnect_s)
                continue

            if not chunk:
                continue
            for line in self._lines.feed(chunk):
                self._rx.put(line + "\n")

    def send_line(self, line: str) -> None:
        text = line if line.endswith("\n") else line + "\n"
        data = text.encode("ascii", errors="replace")
        with self._lock:
            self._last_tx = text
            if not self._write_unlocked(data):
                print("[serial] offline; will resend last status on reconnect", flush=True)

    def try_recv_line(self, timeout: float = 0.0) -> str | None:
        try:
            return self._rx.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            self._close_unlocked()
        self._thread.join(timeout=1.0)


def find_flipper_port() -> str | None:
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
    # Dual-CDC: CLI is usually the first ACM/COM, Clauddey uses the second.
    return hits[-1] if len(hits) > 1 else hits[0]
