import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import ClaudeAgent, CursorAgent
from aggregator import Aggregator
from protocol import parse_command
from router import CommandRouter, LogBackend


class AgentParseTests(unittest.TestCase):
    def test_cursor_mock_event(self):
        ev = CursorAgent().parse_raw(
            {
                "provider": "cursor",
                "event": "composer.state",
                "status": "generating",
                "message": "Generating code...",
            }
        )
        self.assertIsNotNone(ev)
        self.assertEqual(ev.agent, "cursor")
        self.assertEqual(ev.status, "generating")
        self.assertEqual(ev.msg, "Generating code...")

    def test_claude_mock_event(self):
        ev = ClaudeAgent().parse_raw(
            {
                "provider": "claude",
                "event": "cli.session",
                "status": "waiting_for_input",
                "message": "Waiting for approval",
            }
        )
        self.assertIsNotNone(ev)
        self.assertEqual(ev.agent, "claude")
        self.assertEqual(ev.status, "waiting")


class AggregatorTests(unittest.TestCase):
    def test_last_non_idle_wins(self):
        agg = Aggregator()
        cursor = CursorAgent().parse_raw(
            {"provider": "cursor", "status": "generating", "message": "Generating code..."}
        )
        claude = ClaudeAgent().parse_raw(
            {"provider": "claude", "status": "waiting_for_input", "message": "Waiting for approval"}
        )
        self.assertEqual(agg.ingest(cursor).agent, "cursor")
        self.assertEqual(agg.ingest(claude).agent, "claude")
        self.assertIn("claude", agg.state.as_line())

    def test_idle_does_not_steal_other_agent(self):
        agg = Aggregator()
        cursor = CursorAgent().parse_raw(
            {"provider": "cursor", "status": "waiting", "message": "Accept the diff?"}
        )
        idle_claude = ClaudeAgent().parse_raw({"provider": "claude", "status": "idle", "message": ""})
        agg.ingest(cursor)
        self.assertIsNone(agg.ingest(idle_claude))
        self.assertEqual(agg.state.agent, "cursor")


class RouterGateTests(unittest.TestCase):
    def test_monitor_frames_are_blocked(self):
        backend = LogBackend()
        router = CommandRouter(backend=backend)
        cmd = parse_command('{"v":1,"cmd":"ok","agent":"cursor","mode":"monitor"}')
        self.assertFalse(router.handle(cmd, active_agent="cursor"))
        self.assertEqual(backend.history, [])

    def test_missing_mode_is_blocked(self):
        router = CommandRouter(backend=LogBackend())
        cmd = parse_command('{"v":1,"cmd":"ok","agent":"cursor"}')
        self.assertFalse(router.handle(cmd, active_agent="cursor"))

    def test_interactive_routes_by_agent(self):
        backend = LogBackend()
        router = CommandRouter(backend=backend)
        cursor_ok = parse_command(
            '{"v":1,"cmd":"ok","agent":"cursor","mode":"interactive"}'
        )
        claude_cancel = parse_command(
            '{"v":1,"cmd":"cancel","agent":"claude","mode":"interactive"}'
        )
        self.assertTrue(router.handle(cursor_ok, active_agent="cursor"))
        self.assertTrue(router.handle(claude_cancel, active_agent="claude"))
        self.assertEqual(backend.history[0][0], "ctrl+enter")
        self.assertEqual(backend.history[1][0], "ctrl+c")

    def test_dictate_is_host_side(self):
        backend = LogBackend()
        router = CommandRouter(backend=backend)
        cmd = parse_command(
            '{"v":1,"cmd":"dictate","agent":"claude","mode":"interactive"}'
        )
        self.assertTrue(router.handle(cmd, active_agent="claude"))
        self.assertEqual(backend.history[0][0], "os-dictation")
        self.assertIn("not Flipper mic", backend.history[0][1])
