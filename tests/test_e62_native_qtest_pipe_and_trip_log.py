#!/usr/bin/env python3
"""Native ESC no-WFI negative controls: QEMU log must not block QTest."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]


class NativeQTestLogSafety(unittest.TestCase):
    def test_qemu_stderr_is_file_not_undrained_pipe(self):
        code=(ROOT/"tests/e62_autonomous_native_motor_probe.py").read_text()
        self.assertIn('qemu_log_path.open("wb")',code)
        self.assertIn('stderr=qemu_log_handle',code)
        self.assertNotIn('stderr=subprocess.PIPE',code)
        self.assertIn('"source_latched_first_ost3_log"',code)
        self.assertIn('"qtest_last_command_failed"',code)
        self.assertIn('"last_successful_dshot_poll"',code)

    def test_first_trip_is_logged_only_on_the_first_latch_event(self):
        code=(ROOT/"machine/am13e_trip_safety.inc").read_text()
        first=code.index("if (!m->first_ost3_seen)")
        next_condition=code.index("p->reg[0xb0U / 4U] |= new_ost;",first)
        event=code[first:next_condition]
        self.assertIn('error_report("E62_NATIVE_FIRST_OST3 "',event)
        self.assertIn("m->first_ost3_oc_valid",event)
        self.assertIn("m->first_ost3_trip",event)
        self.assertIn("m->first_ost3_cpu_pc",event)
        self.assertEqual(code.count('"E62_NATIVE_FIRST_OST3 "'),1)


if __name__=="__main__":
    unittest.main(verbosity=2)
