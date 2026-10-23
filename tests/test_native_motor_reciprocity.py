#!/usr/bin/env python3
"""Host-only pinned SIM_ONLY instantaneous reciprocity and A/B guard."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_motor_model_profiles import (
    native_motor_parameters, native_motor_model_metadata)
from tools.native_energy_reciprocity_audit import audit_trace
from tools.native_motor_ab_compare import compare_traces
from tools.virtual_bldc import VirtualBLDC


def fixture(profile, *, include_model=True):
    p = native_motor_parameters(profile)
    m = VirtualBLDC(p)
    m.angle_mech_rad = 0.41 / p.pole_pairs
    m.iabc = [1.3, -0.8, -0.5]
    samples = []
    for i, rpm in enumerate((300.0, 625.0, -800.0), start=1):
        m.omega_mech_rad_s = rpm * 2*math.pi/60
        s = m.sample(gate_enabled=True)
        samples.append({
            "wfi": i, "t_ns": i*50000, "integrated_ns": i*48000,
            "motor_rpm": s.mechanical_rpm,
            "electrical_rad": s.electrical_rad,
            "phase_currents_a": list(s.phase_currents_a),
            "bemf_phase_v": list(s.bemf_phase_v),
            "guest_step": 1, "guest_rejected": 0,
        })
    meta = {
        "elf_sha256": "a"*64, "initial_electrical_degrees": -30,
        "required_sectors": 12, "required_integrated_ns": 90000000,
        "host_guest_register_writes": False,
    }
    if include_model:
        meta["motor_model"] = native_motor_model_metadata(profile)
    return {
        "format": "e62.sitl.native-wfi.v1",
        "scope": "SIM_ONLY_UNCALIBRATED_OPEN_STAR_MODEL",
        "metadata": meta, "capture_state": "NATIVE_PROBE_RECORDED",
        "error_type": None,
        "native_result": {
            "significant_direction_reversals": 12 if profile == "legacy" else 0,
            "direction_continuity_qualified_sim_only": profile != "legacy",
        },
        "samples": samples, "events": [],
    }


class ReciprocityTests(unittest.TestCase):
    def test_legacy_power_ratio_seven_is_detected_not_qualified(self):
        data = audit_trace(fixture("legacy"), "legacy")
        self.assertAlmostEqual(data["theoretical_pe_over_pm_ratio"], 7)
        self.assertFalse(data["instantaneous_reciprocity_qualified_sim_only"])
        self.assertAlmostEqual(data["max_relative_power_error"], 6/7, places=10)
        self.assertGreater(data["max_instantaneous_power_error_w"], 0)
        self.assertFalse(data["numerical_energy_balance_qualified"])

    def test_reciprocal_electric_mechanical_exchange_matches(self):
        p = native_motor_parameters("reciprocal")
        self.assertAlmostEqual(p.torque_constant_nm_per_a, 0.14)
        data = audit_trace(fixture("reciprocal"), "reciprocal")
        self.assertEqual(data["theoretical_pe_over_pm_ratio"], 1)
        self.assertTrue(data["instantaneous_reciprocity_qualified_sim_only"])
        self.assertLess(data["max_relative_power_error"], 1e-12)
        self.assertFalse(data["physical_motor_calibrated"])

    def test_source_provenance_mismatch_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "model mismatch"):
            audit_trace(fixture("legacy"), "reciprocal")

    def test_old_trace_requires_explicit_legacy_assumption(self):
        old = fixture("legacy", include_model=False)
        with self.assertRaisesRegex(ValueError, "Pre-profile trace"):
            audit_trace(old, "legacy")
        got = audit_trace(old, "legacy", allow_missing_profile=True)
        self.assertEqual(
            got["profile_provenance"],
            "EXPLICIT_PRE_PROFILE_LEGACY_SOURCE_ASSUMPTION")
        with self.assertRaisesRegex(ValueError, "only allowed for legacy"):
            audit_trace(old, "reciprocal", allow_missing_profile=True)

    def test_native_AB_same_elf_and_no_guest_writes(self):
        baseline = fixture("legacy", include_model=False)
        reciprocal = fixture("reciprocal")
        result = compare_traces(
            baseline, reciprocal, allow_old_baseline=True)
        self.assertEqual(result["baseline"]["motor_model"], "legacy")
        self.assertEqual(result["reciprocal"]["motor_model"], "reciprocal")
        self.assertEqual(result["native_extended_gate_verdict"],
                         "NOT_EXECUTED_BY_COMPARATOR")
        self.assertFalse(result["physical_stability_qualified"])
        reciprocal["metadata"]["elf_sha256"] = "b"*64
        with self.assertRaisesRegex(ValueError, "mismatched original ELF"):
            compare_traces(baseline, reciprocal, allow_old_baseline=True)

    def test_mismatch_or_fake_writes_rejected(self):
        a = fixture("legacy")
        b = fixture("reciprocal")
        b["metadata"]["host_guest_register_writes"] = True
        with self.assertRaisesRegex(ValueError, "prohibit Host Guest"):
            compare_traces(a, b)
        b["metadata"]["host_guest_register_writes"] = False
        b["metadata"]["initial_electrical_degrees"] = 0
        with self.assertRaisesRegex(ValueError, "mismatched original ELF"):
            compare_traces(a, b)

    def test_nonfinite_or_mismatched_BEMF_fails_closed(self):
        d = fixture("reciprocal")
        d["samples"][0]["bemf_phase_v"][0] += 1.0
        with self.assertRaisesRegex(ValueError, "not from the expected"):
            audit_trace(d, "reciprocal")
        d = fixture("reciprocal")
        d["samples"][1]["phase_currents_a"][0] = float("nan")
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            audit_trace(d, "reciprocal")


if __name__ == "__main__":
    unittest.main(verbosity=2)
