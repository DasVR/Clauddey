"""Windows keystroke backend using ctypes + SendInput.

No pyautogui/pynput dependency, just the raw Win32 API (keeps the dependency
list slim). Implements router.py's KeyBackend Protocol (`tap(keys, reason)`).

Assumes the target application already has keyboard focus — the common case,
since the user is normally sitting at the terminal/editor when they press a
Flipper button. Windows' foreground-lock rules (in effect since Windows
2000) block a background process from stealing focus on its own without an
AttachThreadInput/SetForegroundWindow dance against the current foreground
window's thread, so this deliberately does not attempt to change focus; a
window-targeting mode can be layered on top later if needed.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

ULONG_PTR = ctypes.c_size_t  # pointer-sized on both 32- and 64-bit Windows

_VK_NAMES: dict[str, int] = {
    "enter": 0x0D,
    "return": 0x0D,
    "escape": 0x1B,
    "esc": 0x1B,
    "tab": 0x09,
    "space": 0x20,
    "backspace": 0x08,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "page_up": 0x21,
    "page_down": 0x22,
}

_MOD_VK: dict[str, int] = {
    "ctrl": 0x11,  # VK_CONTROL
    "control": 0x11,
    "alt": 0x12,  # VK_MENU
    "shift": 0x10,  # VK_SHIFT
    "win": 0x5B,  # VK_LWIN
}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUT_UNION)]


def _vk_and_shift_for_char(ch: str) -> tuple[int, bool]:
    """Resolve a character to (virtual_key, needs_shift).

    VkKeyScanW packs the virtual-key code in the low byte and a shift-state
    bitmask in the high byte (bit 0 = Shift needed) — e.g. '!' and 'A' live
    on the same physical key as '1' and 'a' but need Shift held. Dropping
    that high byte (as a naive `res & 0xFF` would) silently types the wrong
    character for anything that needs Shift.
    """
    res = user32.VkKeyScanW(ord(ch))
    if res == -1 or (res & 0xFF) == 0xFF:
        raise ValueError(f"cannot map character {ch!r} to a virtual key")
    vk = res & 0xFF
    needs_shift = bool((res >> 8) & 0x01)
    return vk, needs_shift


def parse_chord(chord: str) -> tuple[list[int], int]:
    """Split a chord string like 'ctrl+enter' into ([VK_CONTROL], VK_RETURN)."""
    parts = [p.strip().lower() for p in chord.split("+") if p.strip()]
    if not parts:
        raise ValueError("empty chord")
    *mod_tokens, key_token = parts
    modifiers = [_MOD_VK[m] for m in mod_tokens if m in _MOD_VK]

    if key_token in _VK_NAMES:
        return modifiers, _VK_NAMES[key_token]
    if len(key_token) == 1:
        key, needs_shift = _vk_and_shift_for_char(key_token)
        if needs_shift and _MOD_VK["shift"] not in modifiers:
            modifiers.append(_MOD_VK["shift"])
        return modifiers, key
    raise ValueError(f"unknown key token {key_token!r}")


def _send_vk(vk: int, key_up: bool) -> None:
    inp = INPUT(
        type=INPUT_KEYBOARD,
        union=_INPUT_UNION(
            ki=KEYBDINPUT(
                wVk=vk,
                wScan=0,
                dwFlags=KEYEVENTF_KEYUP if key_up else 0,
                time=0,
                dwExtraInfo=0,
            )
        ),
    )
    sent = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    if sent != 1:
        log.warning("SendInput failed for vk=0x%02X (err=%d)", vk, ctypes.get_last_error())


def send_chord(chord: str) -> None:
    """Press+release *chord* (e.g. 'ctrl+enter'), modifiers held for the key press."""
    modifiers, key = parse_chord(chord)
    for vk in modifiers:
        _send_vk(vk, key_up=False)
    _send_vk(key, key_up=False)
    _send_vk(key, key_up=True)
    for vk in reversed(modifiers):
        _send_vk(vk, key_up=True)


class Win32KeyBackend:
    """Implements router.py's KeyBackend Protocol using real SendInput calls."""

    def tap(self, keys: str, reason: str) -> None:
        try:
            send_chord(keys)
        except ValueError as exc:
            log.warning("cannot send %r (%s): %s", keys, reason, exc)
