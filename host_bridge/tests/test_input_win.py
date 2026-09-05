import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@unittest.skipUnless(sys.platform == "win32", "SendInput backend is Windows-only")
class ChordParsingTests(unittest.TestCase):
    def setUp(self):
        import input_win

        self.input_win = input_win

    def test_single_modifier_plus_named_key(self):
        modifiers, key = self.input_win.parse_chord("ctrl+enter")
        self.assertEqual(modifiers, [0x11])  # VK_CONTROL
        self.assertEqual(key, 0x0D)  # VK_RETURN

    def test_two_modifiers_plus_letter(self):
        modifiers, key = self.input_win.parse_chord("alt+tab")
        self.assertEqual(modifiers, [0x12])  # VK_MENU
        self.assertEqual(key, 0x09)  # VK_TAB

    def test_bare_key_has_no_modifiers(self):
        modifiers, key = self.input_win.parse_chord("escape")
        self.assertEqual(modifiers, [])
        self.assertEqual(key, 0x1B)

    def test_letter_key_resolves_via_vkkeyscan(self):
        modifiers, key = self.input_win.parse_chord("ctrl+c")
        self.assertEqual(modifiers, [0x11])
        self.assertGreater(key, 0)

    def test_empty_chord_raises(self):
        with self.assertRaises(ValueError):
            self.input_win.parse_chord("")

    def test_symbol_needing_shift_gets_shift_added(self):
        # '!' sits on the same physical key as '1' but needs Shift held —
        # this is the exact case a naive VkKeyScanW & 0xFF drops.
        modifiers, key = self.input_win.parse_chord("!")
        self.assertIn(0x10, modifiers)  # VK_SHIFT


if __name__ == "__main__":
    unittest.main()
