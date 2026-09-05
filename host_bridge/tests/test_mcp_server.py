import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aggregator import Aggregator
from mcp_server import build_mcp_server


class McpNotifyTests(unittest.IsolatedAsyncioTestCase):
    async def test_notify_updates_aggregator_and_fires_callback(self):
        """Regression test: clauddey_notify must stay `async def`. The MCP
        framework runs a *sync* tool function in a worker thread with no
        event loop, and on_status_change() below schedules an asyncio task —
        that silently raised "no current event loop in thread" the one time
        this was accidentally a plain `def`, and call_tool() swallowed it
        into a generic "Error executing tool" result."""
        agg = Aggregator()
        changes = []
        server = build_mcp_server(agg, changes.append)

        result = await server.call_tool(
            "clauddey_notify", {"agent": "claude", "status": "waiting", "msg": "Approve?"}
        )

        self.assertFalse(getattr(result, "is_error", False), msg=result)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].agent, "claude")
        self.assertEqual(changes[0].status, "waiting")
        self.assertEqual(agg.state.msg, "Approve?")

    async def test_on_status_change_can_schedule_asyncio_work(self):
        """Exercises the exact failure mode from the bug above: the callback
        itself calls asyncio.ensure_future(), which requires a running loop
        in the *calling* context — proving the tool truly runs on the main
        loop and not an executor thread."""
        agg = Aggregator()
        scheduled = []

        async def _background_write() -> None:
            scheduled.append("wrote")

        def on_status_change(state) -> None:
            asyncio.ensure_future(_background_write())

        server = build_mcp_server(agg, on_status_change)
        await server.call_tool(
            "clauddey_notify", {"agent": "cursor", "status": "done", "msg": "Finished"}
        )
        await asyncio.sleep(0)  # let the scheduled task run
        self.assertEqual(scheduled, ["wrote"])
