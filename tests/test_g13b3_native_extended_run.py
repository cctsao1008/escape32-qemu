#!/usr/bin/env python3
"""Pure audit tests. Synthetic sector fixtures are NOT hardware or ELF evidence."""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_closed_loop_audit import ORIGINAL_REL17_ROUTE
from tools.native_extended_run_gate import check_native_extended_run, ExtendedRunError


def fixture():
    pwm = [
        [0, 0, 0, 4136, 652, 3484],
        [652, 3484, 0, 4136, 0, 0],
        [652, 3484, 0, 0, 0, 4136],
        [0, 0, 652, 3484, 0, 4136],
        [0, 4136, 652, 3484, 0, 0],
        [0, 4136, 0, 0, 652, 3484]
    ]
    sectors = []
    for i in range(12):
        before = i % 6 + 1
        after = before % 6 + 1
        sectors.append({
            "guest_step_before": before, "guest_step_after": after,
            "guest_selected_code_before": ORIGINAL_REL17_ROUTE[before][0],
            "guest_selected_code_after": ORIGINAL_REL17_ROUTE[after][0],
            "prior_source_return": list(ORIGINAL_REL17_ROUTE[before][1]),
            "next_source_return": list(ORIGINAL_REL17_ROUTE[after][1]),
            "pwm_before": pwm[i % 6], "pwm_after": pwm[(i + 1) % 6],
            "accepted_cap1_ticks": 100_000 + i * 2_000_000,
            "serviced_ecap_ticks": 200_000 + i * 2_000_000,
        })
    return {
        "status": "NATIVE_GATE_ON",
        "g13b3l_native_sustained_loop": {
            "qualified": True, "required_sectors": 12,
            "completed_feedback_powered_sectors": 12,
            "sector_evidence": sectors,
            "plant_integrated_ns": 100_000_000,
            "powered_pwm_samples": 1000,
            "simulator_analog_frames": 1000,
            "original_guest_wfi_visits": 1000,
            "motor_started_only_after_cross_phase": True,
            "original_unpowered_timg12_steps": 0,
            "native_effective_power": {
                "gate_connected": True,
                "original_ost2_clear": True,
                "original_ost3_clear": True,
                "qualified_consecutive_wfi": 3,
                "simulated_net_dc_energy_j": 0.01,
                "simulated_net_electromagnetic_work_j": 0.001,
            }
        }
    }


class ExtendedNativeRunUnitTests(unittest.TestCase):
    def test_two_full_original_source_cycles(self):
        verdict = check_native_extended_run(fixture())
        self.assertTrue(verdict["qualified"])
        self.assertEqual(verdict["complete_source_ordered_cycles"], 2)
        self.assertEqual(verdict["hardware_pwm_current_protection_thermal"],
                         "OPEN_NOT_MEASURED")

    def test_not_six_only(self):
        data = fixture()
        x = data["g13b3l_native_sustained_loop"]
        x["sector_evidence"] = x["sector_evidence"][:6]
        x["completed_feedback_powered_sectors"] = 6
        with self.assertRaises(ExtendedRunError):
            check_native_extended_run(data)

    def test_no_fake_native_duration(self):
        data = fixture()
        data["g13b3l_native_sustained_loop"]["plant_integrated_ns"] = 89_000_000
        with self.assertRaisesRegex(ExtendedRunError, "duration"):
            check_native_extended_run(data)

    def test_second_cycle_wrong_sequence_fails(self):
        data = fixture()
        data["g13b3l_native_sustained_loop"]["sector_evidence"][7]["guest_selected_code_after"] = 7
        with self.assertRaisesRegex(ExtendedRunError, "sequence"):
            check_native_extended_run(data)

    def test_skipped_cap1_and_false_power_fail(self):
        data = fixture()
        s = data["g13b3l_native_sustained_loop"]["sector_evidence"]
        s[9]["accepted_cap1_ticks"] = s[8]["accepted_cap1_ticks"]
        with self.assertRaisesRegex(ExtendedRunError, "CAP1 time"):
            check_native_extended_run(data)
        other = fixture()
        other["g13b3l_native_sustained_loop"]["native_effective_power"]["gate_connected"] = False
        with self.assertRaisesRegex(ExtendedRunError, "cross-phase"):
            check_native_extended_run(other)

    def test_unpowered_intermediate_step_fails(self):
        data = fixture()
        data["g13b3l_native_sustained_loop"]["original_unpowered_timg12_steps"] = 1
        with self.assertRaises(ExtendedRunError):
            check_native_extended_run(data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
