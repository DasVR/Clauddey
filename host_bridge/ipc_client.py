"""
Client helper for talking to the running bridge's IPC endpoint.

Mirrors the sibling flipper-claude-buddy project's `_ipc.py`: probes whether
the "socket path" is a real AF_UNIX socket (macOS/Linux) or a marker file
containing `TCP:host:port` (Windows), and connects accordingly, so callers
don't need to know which platform they're on.

Usable as a library (`connect_ipc`) or standalone, as a drop-in for `nc -U`
from shell hook scripts:

    echo '{"action":"notify","agent":"claude","status":"waiting","msg":"Approve?"}' \\
        | python ipc_client.py /tmp/clauddey-bridge.sock
"""

from __future__ import annotations

import os
import socket
import stat
import sys


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


def _main() -> int:
    if len(sys.argv) < 2:
        print("usage: ipc_client.py <socket_path> [timeout_s]", file=sys.stderr)
        return 2
    path = sys.argv[1]
    timeout = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
    payload = sys.stdin.buffer.read()
    try:
        sock = connect_ipc(path, timeout=timeout)
    except Exception as exc:
        print(f"connect failed: {exc}", file=sys.stderr)
        return 1
    with sock:
        sock.sendall(payload)
        sock.shutdown(socket.SHUT_WR)
        reply = sock.recv(65536)
    sys.stdout.buffer.write(reply)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
