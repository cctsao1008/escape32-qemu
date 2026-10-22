#!/usr/bin/env python3
"""Host controls for native Rel17 early BEMF rejection evidence."""
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_bemf_policy_audit import prove_original_early_rejection


def valid(**kwargs):
    p = dict(cap1_ticks=112550, epoch_ticks=50, ticks_per_ms=200000,
             original_ival_us=10000, rejected_before=0, rejected_after=1,
             scheduled_before=2, scheduled_after=2,
             armed_after=1, selected_after=5, selected_before=5,
             epoch_valid_before=1)
    p.update(kwargs)
    return p


class OriginalEarlyRejectionTests(unittest.TestCase):
    def test_real_native_capture_rejected_preserving_armed_route(self):
        proof = prove_original_early_rejection(**valid())
        self.assertEqual(proof.actual_capture_us, 563)
        self.assertEqual(proof.minimum_accepted_capture_us, 5000)
        self.assertTrue(proof.native_bemf_armed_after)

    def test_non_early_edge_cannot_be_called_policy_rejection(self):
        for elapsed, ival in ((5000, 10000), (5200, 10000)):
            with self.subTest(elapsed=elapsed):
                with self.assertRaisesRegex(AssertionError, "earlier"):
                    prove_original_early_rejection(**valid(
                        cap1_ticks=50 + elapsed*200, original_ival_us=ival))

    def test_isr_event_but_no_rejection_evidence_fails(self):
        for rejected in (0, 2):
            with self.subTest(rejected=rejected):
                with self.assertRaisesRegex(AssertionError, "rejected_events"):
                    prove_original_early_rejection(
                        **valid(rejected_after=rejected))

    def test_original_scheduled_or_disarmed_invalidates_negative_control(self):
        for changes in ({"scheduled_after": 3}, {"armed_after": 0},
                        {"selected_after": 2}):
            with self.subTest(changes=changes):
                with self.assertRaises(AssertionError):
                    prove_original_early_rejection(**valid(**changes))

    def test_counter_wrap_is_unsigned_bounded(self):
        proof = prove_original_early_rejection(
            **valid(epoch_ticks=0xfffffff0, cap1_ticks=0x100,
                    original_ival_us=2000))
        self.assertEqual(proof.actual_capture_us, 1)

    def test_missing_calibration_or_epoch_disallowed(self):
        for changes in ({"ticks_per_ms": 0}, {"epoch_valid_before": 0},
                        {"cap1_ticks": 50}):
            with self.subTest(changes=changes):
                with self.assertRaises(AssertionError):
                    prove_original_early_rejection(**valid(**changes))


if __name__ == "__main__":
    unittest.main(verbosity=2)
