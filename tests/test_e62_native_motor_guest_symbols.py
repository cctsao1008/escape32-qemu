#!/usr/bin/env python3
"""Never choose an arbitrary file-static SRAM address for native probes."""
import unittest
from e62_autonomous_native_motor_probe import _resolve_unambiguous_guest_symbols


class OriginalGuestSymbolResolutionTests(unittest.TestCase):
    def test_multiple_armed_file_statics_are_omitted(self):
        output = (
            "20000020 b armed\n"
            "20000038 b armed\n"
            "20000040 B valid_frame_feeds\n"
            "20000044 b step\n"
            "20000044 b step\n"
            "20000050 d throt\n"
        )
        found, unavailable = _resolve_unambiguous_guest_symbols(output)
        self.assertNotIn("armed", found)
        self.assertEqual(unavailable["armed"], "AMBIGUOUS_STATIC_ELF_SYMBOL")
        self.assertEqual(found["valid_frame_feeds"], 0x20000040)
        self.assertEqual(found["step"], 0x20000044)
        self.assertEqual(found["throt"], 0x20000050)

    def test_missing_or_out_of_sram_diagnostics_not_invented(self):
        output = "00004000 D captured_events\n30000000 b armed\n"
        found, unavailable = _resolve_unambiguous_guest_symbols(output)
        self.assertEqual(found, {})
        self.assertEqual(unavailable["armed"],
                         "ORIGINAL_ELF_SYMBOL_NOT_AVAILABLE")
        self.assertEqual(unavailable["captured_events"],
                         "ORIGINAL_ELF_SYMBOL_NOT_AVAILABLE")

    def test_duplicate_critical_guest_step_is_not_guessed(self):
        output = "20000010 b step\n20000014 b step\n20000018 B throt\n"
        found, unavailable = _resolve_unambiguous_guest_symbols(output)
        self.assertNotIn("step", found)
        self.assertEqual(unavailable["step"], "AMBIGUOUS_STATIC_ELF_SYMBOL")
        self.assertEqual(found["throt"], 0x20000018)


if __name__ == "__main__":
    unittest.main(verbosity=2)
