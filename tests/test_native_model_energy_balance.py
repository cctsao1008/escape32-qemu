#!/usr/bin/env python3
"""Host-only G13B3M per-step energy accounting and fail-closed diagnostics."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_motor_model_profiles import (
    native_motor_parameters, native_motor_model_metadata)
from tools.native_power_coupled_plant import NativePowerCoupledBLDC
from tools.native_sitl_failure_diagnostics import model_failure_evidence
from tools.virtual_bldc import MotorSample
from tools.virtual_bldc_feedback import AnalogFrontend
from tools.sitl_trace import SitlTraceRecorder
from tools.native_model_energy_report import check_energy_evidence


class ModelEnergyAccountingTests(unittest.TestCase):
    def motor(self, profile="reciprocal"):
        return NativePowerCoupledBLDC(
            native_motor_parameters(profile),
            initial_electrical_rad=-math.pi/6)

    def test_each_powered_interval_is_accounted_and_fails_open_qualification(self):
        m = self.motor()
        # V -> W in canonical [UH,UL,VH,VL,WH,WL].
        d = (0, 0, .20, 0, 0, .98)
        for _ in range(100):
            m.advance(d, 50e-6, gate_enabled=True)
        e = m.energy_balance()
        self.assertEqual(e["integration_intervals"], 100)
        self.assertEqual(e["powered_intervals"], 100)
        self.assertGreater(e["model_bus_input_energy_j"], 0)
        self.assertGreater(e["winding_copper_loss_energy_j"], 0)
        self.assertTrue(math.isfinite(e["mechanical_kinetic_energy_change_j"]))
        self.assertFalse(e["numerical_energy_balance_qualified"])
        self.assertFalse(e["commutation_current_continuity_qualified"])
        self.assertFalse(e["native_rotor_direction_qualified_by_this_ledger"])
        self.assertAlmostEqual(
            e["integration_residual_excluding_topology_impulses_j"],
            e["raw_energy_balance_residual_j"] +
            e["topology_projection_impulse_energy_j"], places=12)

    def test_commutation_projection_exposes_unmodeled_magnetic_loss(self):
        m = self.motor()
        # V->W, then U->V projects [0,+I,-I] onto [+I/2,-I/2,0].
        m.advance((0, 0, .2, 0, 0, .98), 50e-6, gate_enabled=True)
        old_i = m.iabc[1]
        self.assertGreater(old_i, 0)
        before = m.energy_balance()
        m.advance((.2, 0, 0, .98, 0, 0), 50e-6, gate_enabled=True)
        after = m.energy_balance()
        lost = after["topology_projection_impulse_energy_j"] - (
            before["topology_projection_impulse_energy_j"])
        expected = -.75 * m.p.phase_inductance_h * old_i**2
        self.assertAlmostEqual(lost, expected, places=12)
        self.assertLess(lost, 0)
        self.assertGreater(after["topology_projection_absolute_energy_j"], 0)
        self.assertEqual(after["topology_nonzero_impulses"], 1)
        last = after["first_topology_events"][-1]
        self.assertEqual(last["previous_pair"], [1, 2])
        self.assertEqual(last["next_pair"], [0, 1])
        self.assertFalse(last["physically_resolved_commutation"])

    def test_open_bridge_current_discard_is_explicit_impulse(self):
        m = self.motor()
        m.advance((0, 0, .2, 0, 0, .98), 50e-6, gate_enabled=True)
        old_energy = .5 * m.p.phase_inductance_h * sum(
            x*x for x in m.iabc)
        before = m.energy_balance()
        m.advance((0, 0, 0, 0, 0, 0), 50e-6, gate_enabled=False)
        after = m.energy_balance()
        self.assertEqual(after["coasting_intervals"], 1)
        self.assertEqual(m.iabc, [0, 0, 0])
        self.assertAlmostEqual(
            after["topology_projection_impulse_energy_j"] -
            before["topology_projection_impulse_energy_j"],
            -old_energy, places=12)
        self.assertEqual(after["first_topology_events"][-1]["next_pair"], None)

    def test_unpowered_from_rest_cannot_create_any_energy(self):
        m = self.motor()
        for _ in range(7):
            m.advance((0, 0, 0, .98, 0, 0), 50e-6, gate_enabled=True)
        e = m.energy_balance()
        self.assertEqual(e["integration_intervals"], 7)
        self.assertEqual(e["powered_intervals"], 0)
        self.assertEqual(e["raw_energy_balance_residual_j"], 0)
        self.assertEqual(e["topology_projection_impulse_energy_j"], 0)
        self.assertEqual(e["model_bus_input_energy_j"], 0)
        self.assertEqual(m.sample().mechanical_rpm, 0)

    def test_legacy_accounting_does_not_claim_energy_conservation(self):
        m = self.motor("legacy")
        for _ in range(30):
            m.advance((0, 0, .2, 0, 0, .98), 50e-6, gate_enabled=True)
        self.assertFalse(m.energy_balance()["numerical_energy_balance_qualified"])

    def test_analog_saturation_preserves_unclipped_phase_and_limit(self):
        frontend = AnalogFrontend(
            reference_v=3.3, zero_bemf_bias_v=1.65,
            input_gain_v_per_bemf_v=.02)
        sample = MotorSample(
            mechanical_rpm=5800, electrical_rad=1.4,
            phase_currents_a=(4., -4., 0.),
            bemf_phase_v=(90., -20., -70.),
            electromagnetic_torque_nm=-.05,
            drive_enabled=True)
        with self.assertRaisesRegex(ValueError, "saturated") as ctx:
            frontend.words(sample)
        evidence = model_failure_evidence(
            ctx.exception, frontend=frontend, sample=sample)
        self.assertEqual(evidence["classification"],
                         "ANALOG_FRONTEND_SATURATION")
        for observed, expected in zip(
                evidence["allowable_model_bemf_v"], (-82.5, 82.5)):
            self.assertAlmostEqual(observed, expected, places=10)
        self.assertEqual(evidence["failing_sample"]["overrange_phases"], ["U"])
        self.assertGreater(
            evidence["failing_sample"]["analog_fixture_v_before_adc"][0], 3.3)
        self.assertFalse(evidence["clipped_or_bypassed"])
        self.assertFalse(evidence["native_guest_writes"])

    def test_partial_trace_finish_retains_direction_and_failure(self):
        m = self.motor()
        m.advance((0, 0, .2, 0, 0, .98), 50e-6, gate_enabled=True)
        trace = SitlTraceRecorder(
            elf_sha256="a"*64, initial_electrical_degrees=-30,
            required_sectors=12, required_integrated_ns=90000000,
            motor_model=native_motor_model_metadata("reciprocal"))
        failure = {"classification": "ANALOG_FRONTEND_SATURATION",
                   "clipped_or_bypassed": False}
        trace.finish({
            "qualified": False,
            "completed_feedback_powered_sectors": 10,
            "original_early_rejections": 3,
            "original_rejection_window_resets": 2,
            "sim_only_rotor_motion": {
                "significant_direction_reversals": 7,
                "direction_continuity_qualified_sim_only": False},
            "sim_only_energy_balance": m.energy_balance(),
            "failure_diagnostics": failure,
            "last_complete_analog_injected_wfi": 773,
            "failed_native_wfi_visit": 774,
        })
        doc = trace.document(error_type="AssertionError")
        self.assertEqual(doc["capture_state"], "PARTIAL_EXCEPTION")
        nr = doc["native_result"]
        self.assertFalse(nr["native_six_step_qualified"])
        self.assertEqual(nr["significant_direction_reversals"], 7)
        self.assertEqual(nr["last_complete_analog_injected_wfi"], 773)
        self.assertEqual(nr["failed_native_wfi_visit"], 774)
        self.assertEqual(nr["sim_only_failure_diagnostics"], failure)
        self.assertIsInstance(nr["sim_only_energy_balance"], dict)
        self.assertEqual(nr["extended_strict_verdict"],
                         "NOT_EXECUTED_BY_TRACE_RECORDER")

    def test_read_only_energy_report_checks_closure_without_making_pass(self):
        m = self.motor()
        m.advance((0, 0, .2, 0, 0, .98), 50e-6, gate_enabled=True)
        e = m.energy_balance()
        trace = {
            "format": "e62.sitl.native-wfi.v1",
            "scope": "SIM_ONLY_UNCALIBRATED_OPEN_STAR_MODEL",
            "capture_state": "PARTIAL_EXCEPTION",
            "samples": [{"sim_only_energy_balance": e}],
            "events": [],
            "native_result": {
                "sim_only_energy_balance": e,
                "sim_only_failure_diagnostics": {
                    "classification": "ANALOG_FRONTEND_SATURATION"},
                "failed_native_wfi_visit": 2,
                "last_complete_analog_injected_wfi": 1,
                "significant_direction_reversals": 0,
            },
        }
        report = check_energy_evidence(trace)
        self.assertTrue(report["audit_arithmetic_consistent"])
        self.assertFalse(report["numerical_energy_balance_qualified"])
        self.assertFalse(report["physical_motor_qualified"])
        self.assertFalse(report["strict_rotor_gate_executed_here"])
        tampered = dict(trace)
        tampered["native_result"] = dict(trace["native_result"])
        tampered["native_result"]["sim_only_energy_balance"] = dict(e)
        tampered["native_result"]["sim_only_energy_balance"][
            "raw_energy_balance_residual_j"] += 3
        with self.assertRaisesRegex(ValueError, "Corrupted"):
            check_energy_evidence(tampered)
        tampered = dict(trace)
        tampered["native_result"] = dict(trace["native_result"])
        tampered["native_result"]["sim_only_failure_diagnostics"] = None
        with self.assertRaisesRegex(ValueError, "missing structured failure"):
            check_energy_evidence(tampered)

    def test_failure_without_sample_never_synthesizes_motor_state(self):
        frontend = AnalogFrontend(
            reference_v=3.3, zero_bemf_bias_v=1.65,
            input_gain_v_per_bemf_v=.02)
        result = model_failure_evidence(
            FloatingPointError("Motor diverged"),
            frontend=frontend, sample=None)
        self.assertEqual(result["classification"],
                         "SIM_ONLY_MOTOR_OR_ANALOG_EXCEPTION")
        self.assertIsNone(result["failing_sample"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
