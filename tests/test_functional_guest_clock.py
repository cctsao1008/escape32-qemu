#!/usr/bin/env python3
"""Original Guest SysTick scenario clock must not depend on ECAP enable."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.functional_guest_clock import OriginalGuestTickClock


class FunctionalGuestClockTests(unittest.TestCase):
    def test_running_before_ecap_is_enabled(self):
        clock = OriginalGuestTickClock(14801)
        self.assertEqual(clock.observe(14817), 1_000_000)
        self.assertEqual(clock.observe(14833), 2_000_000)
        self.assertEqual(clock.last_delta_ticks, 16)

    def test_zero_delta_does_not_create_time(self):
        clock = OriginalGuestTickClock(50)
        self.assertEqual(clock.observe(50), 0)
        self.assertEqual(clock.observe(50), 0)
        self.assertEqual(clock.total_zero_delta_observations, 2)
        self.assertEqual(clock.observe(66), 1_000_000)
        self.assertEqual(clock.stalled_observations, 0)

    def test_repeated_stall_fails_closed(self):
        clock = OriginalGuestTickClock(50, max_stalled_observations=2)
        clock.observe(50)
        clock.observe(50)
        with self.assertRaisesRegex(ValueError, 'did not advance'):
            clock.observe(50)

    def test_wraparound(self):
        clock = OriginalGuestTickClock(0xfffffff8)
        self.assertEqual(clock.observe(0x00000008), 1_000_000)

    def test_backward_and_large_jump_rejected(self):
        clock = OriginalGuestTickClock(200)
        with self.assertRaisesRegex(ValueError, 'invalid/too large'):
            clock.observe(199)
        self.assertEqual(clock.elapsed_ns, 0)
        with self.assertRaisesRegex(ValueError, 'invalid/too large'):
            clock.observe(600)
        self.assertEqual(clock.previous_tick, 200)

    def test_invalid_input_rejected(self):
        with self.assertRaises(ValueError):
            OriginalGuestTickClock(-1)
        clock = OriginalGuestTickClock(10)
        with self.assertRaises(ValueError):
            clock.observe(None)


if __name__ == '__main__':
    unittest.main(verbosity=2)
