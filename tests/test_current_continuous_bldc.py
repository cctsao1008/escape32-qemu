#!/usr/bin/env python3
"""Host-only explicit-leg current continuity; no native ESCape32 claim."""
import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.current_continuous_bldc import CurrentContinuousBLDC, LegTopology
from tools.virtual_bldc import MotorParameters


def motor(*, theta=-math.pi/6, diode=0.7):
    p = MotorParameters(
        vbus_v=24.0, phase_resistance_ohm=.3,
        phase_inductance_h=.002, bemf_constant_v_per_rad_s=.02,
        torque_constant_nm_per_a=.14, inertia_kg_m2=1e-6,
        viscous_friction_nm_per_rad_s=.0001,
        load_torque_nm=0, pole_pairs=7)
    return CurrentContinuousBLDC(
        p, initial_electrical_rad=theta, diode_forward_v=diode)


class ExplicitLegCurrentTests(unittest.TestCase):
    def test_switch_state_is_zero_time_no_projection(self):
        m = motor()
        m.set_switches(LegTopology(("H","L","Z")))
        for _ in range(100):
            m.advance(1e-6)
        currents = tuple(m.iabc)
        energy = m.magnetic_energy_j
        self.assertGreater(energy, 0)
        m.set_switches(LegTopology(("Z","H","L")))
        self.assertEqual(tuple(m.iabc), currents)
        self.assertEqual(m.magnetic_energy_j, energy)
        self.assertEqual(m.diagnostics()[
            "forced_current_projection_impulse_energy_j"], 0)
        self.assertEqual(m.diagnostics()["topology_changes"], 2)
        self.assertEqual(m.diagnostics()["first_topology_events"][-1][
            "magnetic_energy_at_switch_j"], energy)

    def test_newly_floating_old_phase_freewheels_via_diode(self):
        m = motor(theta=0.15)
        m.set_switches(LegTopology(("H","L","Z")))
        for _ in range(80):
            m.advance(1e-6)
        current_old = tuple(m.iabc)
        self.assertGreater(current_old[0], 0)
        m.set_switches(LegTopology(("Z","H","L")))
        m.advance(1e-6)
        self.assertEqual(m.last_conduction.states[0], "LOW_DIODE")
        self.assertGreater(m.iabc[0], 0)
        self.assertAlmostEqual(
            m.last_conduction.terminal_voltages_v[0], -0.7)
        self.assertAlmostEqual(sum(m.iabc), 0, places=11)
        self.assertGreater(m.diagnostics()["diode_conduction_intervals"], 0)

    def test_gate_all_off_does_not_discard_magnetic_energy(self):
        m = motor()
        m.set_switches(LegTopology(("H","L","Z")))
        for _ in range(20):
            m.advance(1e-6)
        currents_before = tuple(m.iabc)
        energy_before = m.magnetic_energy_j
        m.set_switches(LegTopology(("Z","Z","Z")))
        self.assertEqual(tuple(m.iabc), currents_before)
        self.assertEqual(m.magnetic_energy_j, energy_before)
        m.advance(1e-6)
        self.assertTrue(
            any("DIODE" in x for x in m.last_conduction.states))
        self.assertGreater(m.magnetic_energy_j, 0)
        self.assertAlmostEqual(sum(m.iabc), 0, places=11)

    def test_all_float_from_zero_has_no_motor_kick(self):
        m = motor()
        for _ in range(100):
            m.advance(1e-6)
        self.assertEqual(m.iabc, [0.0,0.0,0.0])
        self.assertEqual(m.sample().mechanical_rpm, 0)
        e = m.diagnostics()
        self.assertEqual(e["bus_input_energy_j"], 0)
        self.assertEqual(e["winding_magnetic_delta_j"], 0)
        self.assertEqual(e["diode_loss_j"], 0)
        self.assertEqual(e["raw_energy_residual_j"], 0)

    def test_electrical_backward_euler_power_identity(self):
        m = motor(theta=0.25)
        stages = [(("H","L","Z"),100), (("Z","H","L"),100),
                  (("L","H","Z"),100), (("Z","Z","Z"),20)]
        for sw, n in stages:
            m.set_switches(LegTopology(sw))
            for _ in range(n):
                m.advance(1e-6)
        e = m.diagnostics()
        electrical = (
            e["bus_input_energy_j"]-e["diode_loss_j"]-
            e["winding_copper_loss_j"]-e["bemf_conversion_j"]-
            e["winding_magnetic_delta_j"])
        self.assertAlmostEqual(
            electrical,
            e["backward_euler_electrical_numerical_loss_j"],places=10)
        self.assertGreaterEqual(
            e["backward_euler_electrical_numerical_loss_j"],0)
        self.assertGreater(e["diode_loss_j"],0)
        self.assertEqual(e["forced_current_projection_impulse_energy_j"],0)
        self.assertFalse(e["physical_motor_qualified"])
        self.assertFalse(e["real_native_guest_PWM_or_CAP1_qualified"])
        self.assertFalse(e["numeric_timestep_convergence_qualified"])

    def test_sample_explicit_switch_timestep_sensitivity(self):
        def simulate(n):
            m = motor(theta=0.2)
            for switches in (("H","L","Z"),("Z","H","L"),
                             ("Z","Z","Z")):
                m.set_switches(LegTopology(switches))
                for _ in range(60*n):
                    m.advance(2e-6/n)
            return m
        a,b,c = (simulate(n) for n in (1,2,4))
        self.assertGreater(a.integrated_intervals,0)
        self.assertGreater(c.integrated_intervals,b.integrated_intervals)
        self.assertEqual(a.topology_changes,3)
        self.assertEqual(c.topology_changes,3)
        for m in (a,b,c):
            self.assertEqual(m.diagnostics()[
                "forced_current_projection_impulse_energy_j"],0)
            self.assertGreater(
                m.diagnostics()["diode_conduction_intervals"],0)
            self.assertTrue(math.isfinite(m.sample().mechanical_rpm))
            self.assertAlmostEqual(sum(m.iabc),0,places=9)
        err1=abs(a.sample().mechanical_rpm-b.sample().mechanical_rpm)
        err2=abs(b.sample().mechanical_rpm-c.sample().mechanical_rpm)
        self.assertGreater(err1,err2)

    def test_untrusted_duty_ratios_and_invalid_topologies_refused(self):
        for x in ((.5,"L","Z"),("H","L"),("H","LOW","Z"),
                  ["H","L","Z"]):
            with self.assertRaises(ValueError):
                LegTopology(x)
        m=motor()
        with self.assertRaises(TypeError):
            m.set_switches(("H","L","Z"))
        with self.assertRaises(TypeError):
            m.set_switches((.5,0,0,0,0,1))

    def test_nonreciprocal_parameters_cannot_assert_energy_identity(self):
        from dataclasses import replace
        with self.assertRaisesRegex(ValueError,"reciprocal"):
            CurrentContinuousBLDC(replace(
                motor().p,torque_constant_nm_per_a=.02))

    def test_timestep_guard_fails_without_modifying_state(self):
        m=motor(theta=.3)
        m.set_switches(LegTopology(("H","L","Z")))
        m.omega_mech_rad_s=10000
        before=(tuple(m.iabc),m.angle_mech_rad,m.omega_mech_rad_s)
        with self.assertRaisesRegex(ValueError,"step guard"):
            m.advance(1e-4)
        self.assertEqual(
            (tuple(m.iabc),m.angle_mech_rad,m.omega_mech_rad_s),before)
        self.assertEqual(m.integrated_intervals,0)

    def test_zero_diode_drop_is_supported(self):
        m=motor(diode=0)
        m.set_switches(LegTopology(("H","L","Z")))
        m.advance(1e-6)
        self.assertEqual(m.diagnostics()["diode_loss_j"],0)
        self.assertEqual(m.diagnostics()["topology_changes"],1)

    def test_all_off_inductive_current_can_regenerate_via_high_diode(self):
        m=motor(theta=0.2)
        # Controlled host-only initial inductor energy, not a Guest kick.
        m.iabc[:]=[-5.0, 5.0, 0.0]
        before=m.magnetic_energy_j
        m.advance(1e-6)
        self.assertEqual(m.last_conduction.states,
                         ("HIGH_DIODE","LOW_DIODE","OPEN"))
        self.assertLess(m.diagnostics()["bus_input_energy_j"],0)
        self.assertGreater(m.diagnostics()["diode_loss_j"],0)
        self.assertLess(m.magnetic_energy_j,before)
        self.assertAlmostEqual(sum(m.iabc),0,places=11)


if __name__=="__main__":
    unittest.main(verbosity=2)
