#!/usr/bin/env python3
"""Synthetic-only trajectory validation; never a hardware/firmware PASS."""
import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_rotor_motion_audit import NativeRotorMotionAudit


def feed(audit, visit, rpm, *, sectors=6):
    audit.observe(wfi_visit=visit, completed_sectors=sectors,
                  integrated_ns=visit*100000, rpm=rpm,
                  phase_currents_a=(0.5, -0.5, 0),
                  dc_power_w=2)


class NativeRotorMotionUnit(unittest.TestCase):
    def test_stable_direction_sim_only_does_not_approve_hardware(self):
        audit = NativeRotorMotionAudit()
        for n,rpm in enumerate((0, 3, 21, 40, 35, 25), 1):
            feed(audit, n, rpm, sectors=7)
        d=audit.result()
        self.assertEqual(d["significant_direction_reversals"], 0)
        self.assertTrue(d["direction_continuity_qualified_sim_only"])
        self.assertFalse(d["physical_motor_stability_qualified"])

    def test_reverse_after_six_sectors_fails_direction(self):
        audit=NativeRotorMotionAudit()
        for n,rpm in enumerate((0, 11, 65, 4, -3, -15, -330, 0, 22), 1):
            feed(audit,n,rpm,sectors=7)
        d=audit.result()
        self.assertEqual(d["significant_direction_reversals"], 2)
        self.assertFalse(d["direction_continuity_qualified_sim_only"])
        self.assertEqual(d["reversal_examples"][0]["native_wfi_visit"],6)

    def test_earlier_startup_reversals_are_not_endurance_evidence(self):
        audit=NativeRotorMotionAudit()
        feed(audit,1,-100,sectors=5)
        feed(audit,2,100,sectors=5)
        feed(audit,3,22,sectors=6)
        feed(audit,4,20,sectors=6)
        self.assertEqual(audit.result()["significant_direction_reversals"],0)

    def test_bad_model_values_and_time_are_rejected(self):
        audit=NativeRotorMotionAudit()
        feed(audit,1,12)
        with self.assertRaises(ValueError):
            audit.observe(wfi_visit=2, completed_sectors=7,
                          integrated_ns=50000, rpm=12,
                          phase_currents_a=(0,0,0), dc_power_w=1)
        for v in (math.nan, math.inf):
            with self.assertRaises(ValueError):
                audit.observe(wfi_visit=3, completed_sectors=7,
                              integrated_ns=350000, rpm=v,
                              phase_currents_a=(0,0,0), dc_power_w=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
