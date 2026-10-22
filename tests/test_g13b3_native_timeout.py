#!/usr/bin/env python3
"""Original firmware no-valid-BEMF timeout audited without forged state."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_bemf_timeout_qualification import prove_native_no_feedback_timeout


def valid(**changes):
    params = dict(epoch=1000, timeout_ticks=6553600,
                  cap_end_ticks=1000+6555000,
                  armed_before=1, armed_after=0,
                  epoch_valid_before=1, epoch_valid_after=0,
                  ticks_per_ms=200000,
                  captured_before=0, captured_after=0,
                  rejected_before=0, rejected_after=0,
                  cancelled_before=4, cancelled_after=5,
                  ertm_after=100000000,
                  simulator_bemf_words=(0,0,0), physical_tz_flags=0)
    params.update(changes)
    return params


class NativeNoFeedbackTimeoutTests(unittest.TestCase):
    def test_true_original_timeout_without_external_input(self):
        x = prove_native_no_feedback_timeout(**valid())
        self.assertEqual(x.elapsed_since_epoch_ticks, 6555000)
        self.assertEqual(x.original_timg12_cancelled_after, 5)

    def test_early_guest_stop_not_timeout(self):
        with self.assertRaisesRegex(AssertionError, "ECAP time"):
            prove_native_no_feedback_timeout(
                **valid(cap_end_ticks=1000+1000000))

    def test_accepted_irq_or_rejected_irq_not_no_feedback(self):
        for k in ("captured_after", "rejected_after"):
            with self.subTest(k=k):
                with self.assertRaisesRegex(AssertionError, "comparator"):
                    prove_native_no_feedback_timeout(**valid(**{k:1}))

    def test_original_timer_and_policy_are_required(self):
        for change in ({"cancelled_after":4}, {"ertm_after":10000},
                       {"armed_after":1}, {"epoch_valid_after":1},
                       {"ticks_per_ms":100000}):
            with self.subTest(change=change):
                with self.assertRaises(AssertionError):
                    prove_native_no_feedback_timeout(**valid(**change))

    def test_malformed_or_valid_analog_and_real_trip_are_rejected(self):
        for change in ({"simulator_bemf_words":(0,0x10800,0)},
                       {"physical_tz_flags":0x20000},
                       {"simulator_bemf_words":(0x20000,0,0)}):
            with self.subTest(change=change):
                with self.assertRaises(AssertionError):
                    prove_native_no_feedback_timeout(**valid(**change))


if __name__ == "__main__":
    unittest.main(verbosity=2)
