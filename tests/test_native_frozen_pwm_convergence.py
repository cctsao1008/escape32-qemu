#!/usr/bin/env python3
"""Host-only frozen actual-WFI PWM replay, including skipped transitions."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_motor_model_profiles import (
    native_motor_parameters, native_motor_model_metadata)
from tools.native_power_coupled_plant import NativePowerCoupledBLDC
from tools.native_frozen_pwm_convergence import frozen_pwm_convergence
from tools.sitl_trace import FORMAT, SCOPE


def synthetic_native_wfi_trace(profile="reciprocal"):
    p = native_motor_parameters(profile)
    model = NativePowerCoupledBLDC(
        p, initial_electrical_rad=-math.pi/6)
    # Physically sampled phase image: V->W then V->U.
    a = [0,0,200,0,0,980]
    b = [0,980,200,0,0,0]
    records = [
        (a,62500,62500,"SAMPLED_HOLD_INTERVAL"),
        (a,125000,125000,"SAMPLED_HOLD_INTERVAL"),
        (b,177000,125000,"PWM_CHANGE_UNRESOLVED_INTERVAL"),
        (b,230000,178000,"SAMPLED_HOLD_INTERVAL"),
        (b,290000,238000,"SAMPLED_HOLD_INTERVAL"),
    ]
    prev_integrated = 0
    samples = []
    for i,(high,t_ns,integrated,qualifier) in enumerate(records, 1):
        delta = integrated-prev_integrated
        if delta:
            model.advance([h/1000 for h in high],
                          delta/1e9, gate_enabled=True)
        actual = model.sample(gate_enabled=True)
        samples.append({
            "wfi": i, "t_ns": t_ns, "integrated_ns": integrated,
            "pwm_period_ticks": 1000,
            "pwm_high_ticks": high[:],
            "pwm_duties": [h/1000 for h in high],
            "gate_qualified": True, "ost2": False, "ost3": False,
            "sampling_qualifier": qualifier,
            "motor_rpm": actual.mechanical_rpm,
            "electrical_rad": actual.electrical_rad,
            "phase_currents_a": list(actual.phase_currents_a),
            "bemf_phase_v": list(actual.bemf_phase_v),
        })
        prev_integrated = integrated
    return {
        "format": FORMAT, "scope": SCOPE,
        "capture_state": "PARTIAL_EXCEPTION",
        "metadata": {
            "elf_sha256": "a"*64,
            "initial_electrical_degrees": -30,
            "host_guest_register_writes": False,
            "motor_model": native_motor_model_metadata(profile),
        },
        "samples": samples,
        "native_result": {
            "extended_strict_verdict": "NOT_EXECUTED_BY_TRACE_RECORDER",
            "physical_motor_stability_qualified": False,
        },
    }


class FrozenNativePWMTests(unittest.TestCase):
    def test_exact_one_step_replay_matches_existing_model(self):
        d = synthetic_native_wfi_trace()
        r = frozen_pwm_convergence(d)
        self.assertTrue(r["same_source_step1_replay_match"])
        self.assertEqual(r["observed_qualified_integration_intervals"], 4)
        self.assertEqual(r["observed_unresolved_pwm_changes"], 1)
        self.assertEqual(len(r["results"]), 4)
        for run in r["results"]:
            self.assertEqual(run["integrated_intervals"], 4)
            self.assertEqual(
                run["integration_substeps"], run["substeps"]*4)
            self.assertFalse(run["energy"]["numerical_energy_balance_qualified"])
        one=r["results"][0]
        self.assertLess(one["max_abs_rpm_error_vs_native_trace"],1e-8)
        self.assertLess(
            one["max_abs_phase_current_error_a_vs_native_trace"],1e-10)
        self.assertLess(
            one["max_abs_angle_error_rad_vs_native_trace"],1e-10)
        self.assertTrue(r["input_guest_pwm_samples_frozen"])
        self.assertFalse(r["guest_execution_or_feedback_rerun"])
        self.assertFalse(r["numerical_convergence_qualified"])
        self.assertFalse(r["independent_strict_gate_executed"])

    def test_legacy_profile_also_replays(self):
        d=synthetic_native_wfi_trace("legacy")
        r=frozen_pwm_convergence(d,steps=(1,4))
        self.assertEqual(r["model_profile"],"legacy")
        self.assertEqual(len(r["results"]),2)
        self.assertTrue(r["same_source_step1_replay_match"])

    def test_unknown_changed_pwm_interval_cannot_be_integrated(self):
        d=synthetic_native_wfi_trace()
        d["samples"][2]["integrated_ns"] += 1000
        with self.assertRaisesRegex(ValueError,"unresolved PWM"):
            frozen_pwm_convergence(d)

    def test_nonchanging_pwm_cannot_masquerade_as_transition(self):
        d=synthetic_native_wfi_trace()
        d["samples"][2]["pwm_high_ticks"] = d["samples"][1][
            "pwm_high_ticks"][:]
        d["samples"][2]["pwm_duties"] = d["samples"][1]["pwm_duties"][:]
        with self.assertRaisesRegex(ValueError,"transition"):
            frozen_pwm_convergence(d)

    def test_changed_guest_step_does_not_modify_pwm_trace(self):
        d=synthetic_native_wfi_trace()
        d["samples"][2]["guest_step"] = 5
        r=frozen_pwm_convergence(d)
        self.assertTrue(r["same_source_step1_replay_match"])

    def test_corrupted_trace_cannot_claim_step1_reproducibility(self):
        d=synthetic_native_wfi_trace()
        d["samples"][-1]["motor_rpm"] += 10
        with self.assertRaisesRegex(ValueError,"refuse numerical convergence"):
            frozen_pwm_convergence(d)

    def test_untrusted_pulse_and_motor_provenance_fail_closed(self):
        d=synthetic_native_wfi_trace()
        d["samples"][0]["pwm_duties"][2]=.7
        with self.assertRaisesRegex(ValueError,"six actual sampled PWM"):
            frozen_pwm_convergence(d)
        d=synthetic_native_wfi_trace()
        d["metadata"]["motor_model"]["torque_constant_nm_per_a"]=.02
        with self.assertRaisesRegex(ValueError,"provenance"):
            frozen_pwm_convergence(d)

    def test_cannot_replay_unqualified_gate_or_guest_writes(self):
        d=synthetic_native_wfi_trace()
        d["samples"][3]["ost2"]=True
        with self.assertRaisesRegex(ValueError,"Gate/Trip"):
            frozen_pwm_convergence(d)
        d=synthetic_native_wfi_trace()
        d["metadata"]["host_guest_register_writes"]=True
        with self.assertRaisesRegex(ValueError,"Guest-writes"):
            frozen_pwm_convergence(d)


if __name__=="__main__":
    unittest.main(verbosity=2)
