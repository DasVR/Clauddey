"""
Shared helper for Clauddey's Claude Code hook scripts.

Standalone copy of host_bridge/ipc_client.py's connect_ipc(): plugin scripts
run from wherever the plugin is installed, which is not necessarily anywhere
near a host_bridge/ checkout, so this can't just import that module — it
carries its own copy of the same connect logic instead.
"""

from __future__ import annotations

import json
import os
import socket
import stat
import tempfile

SOCKET_PATH = os.environ.get(
    "CLAUDDEY_IPC_SOCKET", os.path.join(tempfile.gettempdir(), "clauddey-bridge.sock")
)


def connect_ipc(path: str, timeout: float | None = None) -> socket.socket:
    is_socket = False
    try:
        is_socket = stat.S_ISSOCK(os.stat(path).st_mode)
    except OSError:
        is_socket = False

    if is_socket and hasattr(socket, "AF_UNIX"):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if timeout is not None:
            s.settimeout(timeout)
        s.connect(path)
        return s

    with open(path, "r", encoding="utf-8") as f:
        marker = f.read(256).strip()
    if not marker.startswith("TCP:"):
        raise RuntimeError(f"unrecognized bridge endpoint marker: {marker!r}")
    host, port = marker[len("TCP:") :].rsplit(":", 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if timeout is not None:
        s.settimeout(timeout)
    s.connect((host, int(port)))
    return s


def notify(agent: str, status: str, msg: str = "", timeout: float = 3.0) -> None:
    """Fire-and-forget status push to the running Clauddey daemon.

    Silently no-ops (never raises) if the daemon isn't running or the push
    fails — a hook must never block or fail the user's Claude Code session
    just because Clauddey happens to be offline.
    """
    if not os.path.exists(SOCKET_PATH):
        return
    try:
        sock = connect_ipc(SOCKET_PATH, timeout=timeout)
        with sock:
            payload = json.dumps({"action": "notify", "agent": agent, "status": status, "msg": msg})
            sock.sendall(payload.encode("utf-8"))
            sock.shutdown(socket.SHUT_WR)
            sock.recv(4096)
    except Exception:
        pass
