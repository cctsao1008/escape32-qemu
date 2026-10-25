#!/usr/bin/env python3
"""Synthetic G15 phase-audit tests; NEVER original Guest rotor evidence."""
import math
import unittest

from tools.native_closed_loop_audit import ORIGINAL_REL17_ROUTE
from tools.native_rotor_phase_audit import (
    NativeRotorPhaseAudit, _source_field_target_deg
)


class RotorPhaseAuditTests(unittest.TestCase):
    def point(self, audit, visit, sectors, angle_deg, rpm=150.0,
              reverse_current=False, mismatch=False):
        step = (sectors % 6) + 1
        src, sink = ORIGINAL_REL17_ROUTE[step][1]
        currents = [0.0, 0.0, 0.0]
        currents[src] = -1.0 if reverse_current else 1.0
        currents[sink] = 1.0 if reverse_current else -1.0
        pair = ((sink, src) if mismatch else (src, sink))
        return audit.observe(
            wfi_visit=visit,
            integrated_ns=visit * 80000,
            completed_sectors=sectors,
            guest_step=step,
            electrical_rad=math.radians(angle_deg % 360),
            mechanical_rpm=rpm,
            phase_currents_a=tuple(currents),
            torque_constant_nm_per_a=0.14,
            observed_pair=pair)

    def test_source_field_target_derived_from_pinned_route(self):
        targets = [_source_field_target_deg(s) for s in range(1, 7)]
        for n, deg in enumerate(targets):
            self.assertAlmostEqual((deg - 60*n + 180) % 360 - 180, 0.0, delta=1e-9)

    def test_unwrap_continuous_forward_full_cycle_and_sector_provenance(self):
        a = NativeRotorPhaseAudit()
        for n in range(7):
            self.point(a, n+1, n, -30.0+60.0*n)
        d = a.result()
        self.assertEqual(len(d["observed_sector_checkpoints"]), 6)
        self.assertAlmostEqual(
            d["last_observation"]["rotor_advance_since_first_wfi_deg"], 360.0)
        self.assertAlmostEqual(
            d["last_observation"]["commanded_minus_rotor_advance_deg"], 0.0)
        self.assertEqual(d["negative_electromagnetic_torque_wfi_samples"], 0)
        self.assertEqual(d["source_pair_mismatch_wfi_samples"], 0)
        self.assertEqual(d["post_six_sector_wfi_samples"], 1)
        self.assertIsNone(d["first_direction_reversal"])
        self.assertFalse(d["hardware_stability_qualified"])

    def test_detect_reverse_with_angle_and_torque_not_just_sign(self):
        a = NativeRotorPhaseAudit()
        for n in range(7):
            self.point(a, n+1, n, -30.0+60.0*n)
        self.point(a, 8, 7, 20.0, rpm=-35, reverse_current=True)
        d = a.result()
        first = d["first_direction_reversal"]
        self.assertIsNotNone(first)
        self.assertEqual(first["native_wfi_visit"], 8)
        self.assertEqual(first["guest_step"], 2)
        self.assertEqual(first["completed_guest_sectors"], 7)
        self.assertLess(first["actual_current_vector_torque_nm"], 0)
        self.assertLess(first["mechanical_rpm"], 0)
        self.assertGreater(
            first["commanded_minus_rotor_advance_deg"], 0)
        self.assertEqual(d["negative_mechanical_rpm_wfi_samples"], 1)
        self.assertEqual(d["negative_electromagnetic_torque_wfi_samples"], 1)
        self.assertFalse(d["original_firmware_or_strict_gate_qualified"])

    def test_mismatched_observed_pair_is_explicit_diagnostic(self):
        a = NativeRotorPhaseAudit()
        for n in range(7):
            self.point(a, n+1, n, -30.0+60.0*n)
        self.point(a, 8, 7, 30.0, mismatch=True)
        d = a.result()
        self.assertEqual(d["source_pair_mismatch_wfi_samples"], 1)
        self.assertFalse(d["last_observation"]["observed_pair_matches_step"])

    def test_fail_closed_on_skipped_wfi_or_angle_alias(self):
        a = NativeRotorPhaseAudit()
        self.point(a, 1, 0, -30.0)
        with self.assertRaisesRegex(ValueError, "Nonconsecutive"):
            self.point(a, 3, 1, 0.0)
        with self.assertRaisesRegex(ValueError, "safely unwrapped"):
            self.point(a, 2, 1, 149.0)
        self.assertEqual(a.result()["actual_observed_guest_wfi_samples"], 1)


if __name__ == "__main__":
    unittest.main()
