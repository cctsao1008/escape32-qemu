#!/usr/bin/env python3
"""Synthetic negative controls for G20 original-Guest pre-CAP1 forensic."""
import copy
import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.native_precapture_dynamics_audit import audit


def fixture():
    rpm = [5., 7., -14., 6., 8., 12.]
    result = []
    for n, value in enumerate(rpm, 1):
        result.append({
            "wfi": n, "t_ns": n * 100,
            "motor_rpm": value, "electrical_rad": .4,
            "phase_currents_a": [1., -1., 0.] if n < 3 else [-1., 1., 0.],
            "guest_step": 1, "guest_selected_code": 5,
            "pwm_high_ticks": [0, 0, 0, 4135, 100, 4030],
            "gate_qualified": True, "ost2": False, "ost3": False,
            "sampling_qualifier": "EXTERNAL_CLOCKED_CURRENT_CONTINUOUS_NO_AVERAGE",
        })
    return {
        "format": "e62.sitl.native-wfi.v1",
        "scope": "SIM_ONLY_UNCALIBRATED_OPEN_STAR_MODEL",
        "metadata": {"host_guest_register_writes": False,
                     "elf_sha256": "a" * 64,
                     "motor_model": {
                         "torque_constant_nm_per_a": .0649,
                         "electromagnetic_reciprocal": True,
                         "physical_motor_calibrated": False,
                         "profile": "ecx87-kv147"}},
        "events": [{"kind": "CAP1_ACCEPTED", "t_ns": 550, "sector": 1}],
        "samples": result,
    }


class PreFirstCAP1MotorDynamicsTests(unittest.TestCase):
    def test_first_sign_change_and_wfi_torque_are_distinct_observations(self):
        report = audit(fixture())
        self.assertEqual(report["pre_first_cap1_wfi_count"], 5)
        self.assertEqual(report["observed_pre_cap1_speed_sign_change_count"], 2)
        self.assertEqual(report["first_pre_cap1_speed_sign_change"]["bracket_ns"],
                         [200, 300])
        self.assertEqual(report["first_pre_cap1_speed_sign_change"]["wfi_after"], 3)
        self.assertEqual(report["first_pre_cap1_negative_torque_wfi"]["wfi"], 3)
        self.assertEqual(report["first_pre_cap1_deceleration_interval"]
                         ["wfi_after"], 3)
        self.assertLess(report["first_pre_cap1_speed_sign_change"]
                        ["mean_observed_acceleration_rad_s2"], 0)
        self.assertEqual([x["wfi"] for x in report[
            "first_speed_sign_change_wfi_window"]], [1, 2, 3, 4, 5])
        self.assertFalse(report["physical_motor_qualified"])
        self.assertFalse(report["guest_writes"])
        self.assertFalse(report["strict_gate_modified"])

    def test_post_cap1_flips_are_not_pre_cap1_flips(self):
        d = fixture()
        d["events"][0]["t_ns"] = 350
        report = audit(d)
        self.assertEqual(report["pre_first_cap1_wfi_count"], 3)
        self.assertEqual(report["observed_pre_cap1_speed_sign_change_count"], 1)
        self.assertEqual(report["first_pre_cap1_speed_sign_change"]
                         ["bracket_ns"], [200, 300])

    def test_missing_currents_fail_closed(self):
        d = fixture()
        d["samples"][1].pop("phase_currents_a")
        with self.assertRaisesRegex(ValueError, "three-phase"):
            audit(d)

    def test_no_fake_guest_or_unclocked_source(self):
        d = fixture()
        d["metadata"]["host_guest_register_writes"] = True
        with self.assertRaisesRegex(ValueError, "unchanged original Guest"):
            audit(d)
        d = fixture()
        d["samples"][2]["sampling_qualifier"] = "SAMPLED_HOLD_INTERVAL"
        with self.assertRaisesRegex(ValueError, "provenance"):
            audit(d)

    def test_first_cap1_and_wfi_order_must_exist(self):
        d = fixture()
        d["events"] = []
        with self.assertRaisesRegex(ValueError, "accepted CAP1"):
            audit(d)
        d = fixture()
        d["samples"][3]["t_ns"] = 100
        with self.assertRaisesRegex(ValueError, "chronology"):
            audit(d)

    def test_not_claiming_negative_torque_without_negative_current_vector(self):
        d = fixture()
        for s in d["samples"]:
            s["phase_currents_a"] = [0., 0., 0.]
        report = audit(d)
        self.assertIsNone(report["first_pre_cap1_negative_torque_wfi"])
        self.assertIsNone(report["first_pre_cap1_positive_rpm_negative_torque_wfi"])
        self.assertEqual(report["sampled_min_pre_cap1_torque_nm"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
