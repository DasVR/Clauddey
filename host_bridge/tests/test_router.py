import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import make_event
from aggregator import Aggregator
from protocol import parse_command
from router import CommandRouter, DictationBackend, LogBackend


class FakeDictationBackend(DictationBackend):
    def __init__(self) -> None:
        self.history: list[str] = []

    def toggle(self, reason: str) -> None:
        self.history.append(reason)


class MakeEventTests(unittest.TestCase):
    def test_normalizes_agent_and_status(self):
        ev = make_event("cursor", "generating", "Generating code...")
        self.assertEqual(ev.agent, "cursor")
        self.assertEqual(ev.status, "generating")
        self.assertEqual(ev.msg, "Generating code...")

    def test_status_alias_is_normalized(self):
        ev = make_event("claude", "waiting_for_input", "Waiting for approval")
        self.assertEqual(ev.agent, "claude")
        self.assertEqual(ev.status, "waiting")


class AggregatorTests(unittest.TestCase):
    def test_last_non_idle_wins(self):
        agg = Aggregator()
        cursor = make_event("cursor", "generating", "Generating code...")
        claude = make_event("claude", "waiting_for_input", "Waiting for approval")
        self.assertEqual(agg.ingest(cursor).agent, "cursor")
        self.assertEqual(agg.ingest(claude).agent, "claude")
        self.assertIn("claude", agg.state.as_line())

    def test_idle_does_not_steal_other_agent(self):
        agg = Aggregator()
        cursor = make_event("cursor", "waiting", "Accept the diff?")
        idle_claude = make_event("claude", "idle", "")
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

    def test_dictate_toggles_the_dictation_backend_not_the_keychord_backend(self):
        backend = LogBackend()
        dictation = FakeDictationBackend()
        router = CommandRouter(backend=backend, dictation=dictation)
        cmd = parse_command(
            '{"v":1,"cmd":"dictate","agent":"claude","mode":"interactive"}'
        )
        self.assertTrue(router.handle(cmd, active_agent="claude"))
        self.assertEqual(dictation.history, ["claude/dictate"])
        self.assertEqual(backend.history, [])  # dictate must never hit the keychord backend
