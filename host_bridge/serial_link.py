"""
Non-blocking USB serial transport.

A reader thread copies complete lines into a queue. The main loop never blocks
on Serial.read(). Writes are mutex-protected and flushed immediately.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from typing import Protocol


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


class SerialTransport:
    def __init__(self, port: str, baud: int = 115200) -> None:
        try:
            import serial  # type: ignore
        except ImportError as exc:
            raise SystemExit("pyserial is required: pip install pyserial") from exc

        self._serial = serial.Serial(port=port, baudrate=baud, timeout=0.05, write_timeout=0.2)
        self._rx: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._buf = bytearray()
        self._thread = threading.Thread(target=self._read_loop, name="clauddey-cdc", daemon=True)
        self._thread.start()
        print(f"[serial] opened {port} @ {baud}", flush=True)

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                chunk = self._serial.read(64)
            except Exception as exc:  # port yanked
                print(f"[serial] read error: {exc}", file=sys.stderr)
                time.sleep(0.25)
                continue
            if not chunk:
                continue
            self._buf.extend(chunk)
            while True:
                nl = self._buf.find(b"\n")
                if nl < 0:
                    if len(self._buf) > 256:
                        self._buf.clear()
                    break
                line = bytes(self._buf[: nl + 1]).decode("ascii", errors="replace")
                del self._buf[: nl + 1]
                self._rx.put(line)

    def send_line(self, line: str) -> None:
        data = (line if line.endswith("\n") else line + "\n").encode("ascii", errors="replace")
        with self._lock:
            self._serial.write(data)
            self._serial.flush()

    def try_recv_line(self, timeout: float = 0.0) -> str | None:
        try:
            return self._rx.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        self._stop.set()
        try:
            self._serial.close()
        except Exception:
            pass


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
