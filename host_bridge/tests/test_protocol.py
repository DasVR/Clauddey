import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from protocol import pack_status, parse_command, ascii_clip, normalize_status


class ProtocolTests(unittest.TestCase):
    def test_pack_status_is_compact_json_line(self):
        line = pack_status("cursor", "generating", "Generating code...")
        self.assertTrue(line.endswith("\n"))
        self.assertIn('"agent":"cursor"', line)
        self.assertIn('"status":"generating"', line)

    def test_waiting_alias(self):
        self.assertEqual(normalize_status("waiting_for_input"), "waiting")

    def test_ascii_clip(self):
        self.assertEqual(ascii_clip("ok ✓", 10), "ok ?")
        self.assertEqual(len(ascii_clip("x" * 80)), 40)

    def test_parse_interactive_command(self):
        cmd = parse_command(
            '{"v":1,"cmd":"ok","agent":"cursor","mode":"interactive"}'
        )
        self.assertIsNotNone(cmd)
        self.assertTrue(cmd.is_interactive)
        self.assertEqual(cmd.cmd, "ok")

    def test_parse_rejects_unknown_cmd(self):
        self.assertIsNone(parse_command('{"cmd":"launch-missiles","mode":"interactive"}'))
