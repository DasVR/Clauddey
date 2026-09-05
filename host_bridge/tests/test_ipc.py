import asyncio
import json
import os
import socket
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aggregator import Aggregator
from ipc_client import connect_ipc
from ipc_server import IpcServer


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _client_roundtrip(socket_path: str, payload: bytes) -> dict:
    sock = connect_ipc(socket_path, timeout=5.0)
    with sock:
        sock.sendall(payload)
        sock.shutdown(socket.SHUT_WR)
        return json.loads(sock.recv(65536).decode("utf-8"))


class IpcRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def test_notify_updates_aggregator_and_replies_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            socket_path = os.path.join(tmp, "clauddey-test.sock")
            agg = Aggregator()
            changes = []
            server = IpcServer(
                agg, changes.append, socket_path=socket_path, tcp_port=_free_tcp_port()
            )
            await server.start()
            try:
                payload = json.dumps(
                    {"action": "notify", "agent": "claude", "status": "waiting", "msg": "Approve?"}
                ).encode("utf-8")
                reply = await asyncio.to_thread(_client_roundtrip, socket_path, payload)
            finally:
                await server.stop()

            self.assertEqual(reply, {"status": "ok"})
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0].agent, "claude")
            self.assertEqual(changes[0].status, "waiting")

    async def test_unknown_action_is_reported_as_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            socket_path = os.path.join(tmp, "clauddey-test2.sock")
            agg = Aggregator()
            server = IpcServer(
                agg, lambda state: None, socket_path=socket_path, tcp_port=_free_tcp_port()
            )
            await server.start()
            try:
                payload = json.dumps({"action": "bogus"}).encode("utf-8")
                reply = await asyncio.to_thread(_client_roundtrip, socket_path, payload)
            finally:
                await server.stop()

            self.assertEqual(reply["status"], "error")

    async def test_idle_event_from_a_different_agent_does_not_fire_the_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            socket_path = os.path.join(tmp, "clauddey-test3.sock")
            agg = Aggregator()
            changes = []
            server = IpcServer(
                agg, changes.append, socket_path=socket_path, tcp_port=_free_tcp_port()
            )
            await server.start()
            try:
                busy = json.dumps(
                    {"action": "notify", "agent": "cursor", "status": "waiting", "msg": "Accept?"}
                ).encode("utf-8")
                await asyncio.to_thread(_client_roundtrip, socket_path, busy)

                idle = json.dumps(
                    {"action": "notify", "agent": "claude", "status": "idle", "msg": ""}
                ).encode("utf-8")
                await asyncio.to_thread(_client_roundtrip, socket_path, idle)
            finally:
                await server.stop()

            self.assertEqual(len(changes), 1)  # the idle claude event must not have fired
            self.assertEqual(agg.state.agent, "cursor")


if __name__ == "__main__":
    unittest.main()
