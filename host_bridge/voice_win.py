"""Windows dictation backend: toggles built-in Voice Typing via Win+H.

There is no reliable public Win32 API to query whether Voice Typing is
currently listening (unlike macOS's `pmset -g assertions` trick), so
`is_active()` is an honest "we can't verify" fail-safe: it stays True from
the moment dictation is toggled on until the router toggles it again. If
that ever drifts out of sync with reality, the user just presses the
Flipper's dictate control again.
"""

from __future__ import annotations

import logging

from input_win import _MOD_VK, _send_vk
from router import DictationBackend

log = logging.getLogger(__name__)

_VK_H = 0x48


class Win32DictationBackend(DictationBackend):
    def __init__(self) -> None:
        self._active = False

    def toggle(self, reason: str) -> None:
        win_vk = _MOD_VK["win"]
        _send_vk(win_vk, key_up=False)
        _send_vk(_VK_H, key_up=False)
        _send_vk(_VK_H, key_up=True)
        _send_vk(win_vk, key_up=True)
        self._active = not self._active
        log.info("%s -> Win+H (dictation now %s, unverified)", reason, "on" if self._active else "off")

    def is_active(self) -> bool:
        return self._active
