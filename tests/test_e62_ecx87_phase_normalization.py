#!/usr/bin/env python3
"""Maxon EC87 terminal/phase BLDC conversion; independent host math gates.

No original Guest modification, no P0/P1 acceptance waiver and no
claim to measured phase waveform or propeller loading.
Source: maxon EC 87 flat UAV, April 2025 datasheet, page 1, KV147.
"""
import math
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.native_motor_model_profiles import native_motor_parameters
from tools.virtual_bldc import VirtualBLDC


class ECX87PhaseNormalizationTests(unittest.TestCase):
    def test_datasheet_kv147_and_terminal_kt_are_mutually_consistent(self):
        terminal_kt = 0.0649  # Nm/A, maxon April 2025, p1
        kv = 147.0  # mechanical rpm per terminal V
        ke_terminal = 60.0/(2.0*math.pi*kv)
        self.assertLess(abs(terminal_kt/ke_terminal-1.0), .01)
        p = native_motor_parameters("ecx87-kv147")
        self.assertAlmostEqual(p.torque_constant_nm_per_a*math.sqrt(3),
                               terminal_kt, places=12)
        self.assertAlmostEqual(p.bemf_constant_v_per_rad_s*p.pole_pairs,
                               p.torque_constant_nm_per_a, places=12)
        # Phase-peak, not line-line terminal and not electrical omega.
        self.assertAlmostEqual(p.bemf_constant_v_per_rad_s,
                               terminal_kt/(21*math.sqrt(3)), places=12)

    def test_no_load_line_to_line_bemf_agrees_with_24v_3500rpm(self):
        p = native_motor_parameters("ecx87-kv147")
        rpm = 3500.0  # no-load speed at 24V on datasheet
        omega_mech = rpm * 2.0*math.pi/60
        ll_peak_v = math.sqrt(3.0)*p.torque_constant_nm_per_a*omega_mech
        self.assertAlmostEqual(ll_peak_v, 23.7870923754, places=6)
        self.assertLess(abs(ll_peak_v-24.0), .5)
        old_wrong_ll_peak = math.sqrt(3.0)*0.0649*omega_mech
        self.assertGreater(old_wrong_ll_peak, 40.0)
        self.assertLess(ll_peak_v/old_wrong_ll_peak, .60)

    def test_resistance_inductance_inertia_and_mechanical_tau(self):
        p = native_motor_parameters("ecx87-kv147")
        self.assertAlmostEqual(2*p.phase_resistance_ohm, 0.106)
        self.assertAlmostEqual(2*p.phase_inductance_h, 48e-6)
        self.assertAlmostEqual(p.inertia_kg_m2, 1300e-7)
        tau_ms = p.inertia_kg_m2*0.106/(0.0649**2)*1e3
        self.assertAlmostEqual(tau_ms, 3.27159717094689, places=7)
        self.assertLess(abs(tau_ms-3.26), .03)

    def test_phase_bemf_and_torque_reciprocal_for_arbitrary_currents(self):
        p = native_motor_parameters("ecx87-kv147")
        m = VirtualBLDC(p)
        m.angle_mech_rad = -0.46/p.pole_pairs
        m.omega_mech_rad_s = 53.0
        for currents in ((0.0, -14.0, 14.0),
                         (12.0, 4.0, -16.0),
                         (-3.5, 6.5, -3.0)):
            m.iabc = list(currents)
            x = m.sample(gate_enabled=True)
            electromagnetic_power = sum(
                v*i for v,i in zip(x.bemf_phase_v,x.phase_currents_a))
            shaft_power = x.electromagnetic_torque_nm*m.omega_mech_rad_s
            self.assertAlmostEqual(electromagnetic_power, shaft_power, places=10)

    def test_fixed_w_high_v_low_pair_changes_torque_with_rotor_pose(self):
        p = native_motor_parameters("ecx87-kv147")
        m = VirtualBLDC(p)
        m.iabc = [0.0, -10.0, 10.0]
        m.angle_mech_rad = math.radians(-30)/p.pole_pairs
        positive = m.sample().electromagnetic_torque_nm
        self.assertAlmostEqual(positive, 1.5*10*p.torque_constant_nm_per_a)
        m.angle_mech_rad = math.radians(100)/p.pole_pairs
        self.assertLess(m.sample().electromagnetic_torque_nm, 0.0)
        # The sign change under an unchanged pair is physically
        # geometric, NOT evidence of a reversed PWM or BEMF phase order.

    def test_native_c_source_uses_same_phase_constant_everywhere(self):
        plant = (ROOT/"machine/am13e_native_motor_plant.inc").read_text()
        dynamics = (ROOT/"machine/am13e_native_motor_dynamics.inc").read_text()
        frontend = (ROOT/"machine/am13e_native_analog_frontend.inc").read_text()
        terminal = re.search(
            r"#define AM13E_NATIVE_KT_TERMINAL \\(m->model_profile == 210U "
            r"\\? ([0-9.]+) : ([0-9.]+)\\)", plant)
        self.assertIsNotNone(terminal)
        self.assertEqual(float(terminal.group(1)), 0.0454)
        self.assertEqual(float(terminal.group(2)), 0.0649)
        for profile,expected in (("ecx87-kv147",0.0649),
                                 ("ecx87-kv210",0.0454)):
            p=native_motor_parameters(profile)
            self.assertAlmostEqual(
                p.torque_constant_nm_per_a*math.sqrt(3.0),expected,places=12)
            self.assertAlmostEqual(
                p.bemf_constant_v_per_rad_s*p.pole_pairs,
                p.torque_constant_nm_per_a,places=12)
        self.assertIn(
            "AM13E_NATIVE_K_PHASE (AM13E_NATIVE_KT_TERMINAL / 1.7320508075688772935)",
            plant)
        self.assertIn("e[p] = AM13E_NATIVE_K_PHASE*m->omega*basis[p]", dynamics)
        self.assertIn("torque *= AM13E_NATIVE_K_PHASE", dynamics)
        self.assertIn("double bemf = AM13E_NATIVE_K_PHASE*m->omega*", frontend)
        self.assertNotRegex(dynamics, r"\bAM13E_NATIVE_KT\b")
        self.assertNotRegex(frontend, r"\bAM13E_NATIVE_KT\b")


if __name__ == "__main__":
    unittest.main(verbosity=2)
