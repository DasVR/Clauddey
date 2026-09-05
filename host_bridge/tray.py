"""Minimal system tray icon for the Clauddey daemon (pystray + Pillow).

Shows connection status as an icon color and offers a Quit item. Runs on its
own thread since pystray's Icon.run() blocks; the Quit callback hands control
back to the asyncio loop via a thread-safe call.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

import pystray
from PIL import Image, ImageDraw

_COLORS: dict[str, tuple[int, int, int]] = {
    "connecting": (200, 160, 40),
    "connected": (40, 170, 80),
    "disconnected": (170, 60, 60),
}


def _make_icon(color: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 56, 56), fill=color)
    return img


class Tray:
    """Tray icon reflecting Clauddey's connection state, with a Quit item."""

    def __init__(self, on_quit: Callable[[], None]) -> None:
        self._on_quit = on_quit
        self._icon = pystray.Icon(
            "clauddey",
            _make_icon(_COLORS["connecting"]),
            "Clauddey (connecting...)",
            menu=pystray.Menu(pystray.MenuItem("Quit", self._quit)),
        )
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._icon.run, name="clauddey-tray", daemon=True)
        self._thread.start()

    def set_status(self, status: str) -> None:
        if status not in _COLORS:
            return
        self._icon.icon = _make_icon(_COLORS[status])
        self._icon.title = f"Clauddey ({status})"

    def _quit(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        icon.stop()
        self._on_quit()

    def stop(self) -> None:
        self._icon.stop()
