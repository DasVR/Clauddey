import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aggregator import Aggregator
from bridge import DEMO_CLAUDE_RAW, DEMO_CURSOR_RAW, push_event
from agents import ClaudeAgent, CursorAgent
from serial_link import StdoutTransport


class DemoPipelineTests(unittest.TestCase):
    def test_mock_events_are_bundled_and_sent(self):
        agg = Aggregator()
        transport = StdoutTransport()

        push_event(agg, transport, CursorAgent().parse_raw(DEMO_CURSOR_RAW))
        push_event(agg, transport, ClaudeAgent().parse_raw(DEMO_CLAUDE_RAW))

        self.assertEqual(len(transport.sent), 2)
        self.assertIn('"agent":"cursor"', transport.sent[0])
        self.assertIn('"status":"generating"', transport.sent[0])
        self.assertIn('"agent":"claude"', transport.sent[1])
        self.assertIn('"status":"thinking"', transport.sent[1])
        self.assertTrue(all(line.endswith("\n") for line in transport.sent))
