#!/usr/bin/env python3
"""G9b: Python motor integrates observed six-output duty, not commands."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.virtual_bldc import (
    MotorParameters, PWMObservation, VirtualBLDC, update_from_mcpwm,
    gate_and_pads_connected, OBS_BASE, GPIO1_BASE, GATE_EN,
    PINCM_BASE, MCPWM4_ROUTES
)


def parameters():
    # Hypothetical simulation fixture, NOT any selected motor's measured
    # R/L/Kv/Ke/Kt/J/B or Quanta ESC qualification values.
    return MotorParameters(
        vbus_v=24.0, phase_resistance_ohm=0.3,
        phase_inductance_h=0.002,
        bemf_constant_v_per_rad_s=0.02,
        torque_constant_nm_per_a=0.02,
        inertia_kg_m2=0.001,
        viscous_friction_nm_per_rad_s=0.001,
        load_torque_nm=0.0, pole_pairs=7
    )


class MotorPlantTest(unittest.TestCase):
    def test_zero_at_rest_without_gate(self):
        m = VirtualBLDC(parameters())
        for _ in range(100):
            state = m.advance((0.5, 0, 0, 0.5, 0, 0), 0.00001,
                              gate_enabled=False)
        self.assertEqual(state.mechanical_rpm, 0.0)
        self.assertEqual(state.bemf_phase_v, (0.0, 0.0, 0.0))
        self.assertEqual(state.phase_currents_a, (0.0, 0.0, 0.0))

    def test_motor_responds_to_six_gates_not_throttle(self):
        m = VirtualBLDC(parameters())
        for _ in range(200):
            state = m.advance((0.75, 0, 0, 0.75, 0, 0), 0.00001,
                              gate_enabled=True)
        self.assertTrue(any(abs(x) > 0 for x in state.phase_currents_a))
        self.assertTrue(abs(state.mechanical_rpm) > 0)
        self.assertTrue(any(abs(x) > 0 for x in state.bemf_phase_v))

    def test_rejects_unmodeled_overlap(self):
        m = VirtualBLDC(parameters())
        with self.assertRaisesRegex(ValueError, "overlapping"):
            m.advance((0.8, 0.4, 0, 0, 0, 0), 1e-5,
                      gate_enabled=True)

    def test_observer_uses_actual_six_counts(self):
        data = {OBS_BASE: 0xf, OBS_BASE+8: 100,
                OBS_BASE+0x14: 0x3f}
        for i, n in enumerate((25, 0, 40, 0, 60, 0)):
            data[OBS_BASE+0x18+i*4] = n
        o = PWMObservation.from_qemu(lambda addr: data.get(addr, 0))
        self.assertEqual(o.high_ticks, (25, 0, 40, 0, 60, 0))
        self.assertEqual(o.six_duties, (.25, 0, .4, 0, .6, 0))
        m = VirtualBLDC(parameters())
        state = update_from_mcpwm(m, lambda addr: data.get(addr, 0),
                                  gate_enabled=True)
        self.assertTrue(all(math.isfinite(x) for x in state.bemf_phase_v))
        self.assertEqual(m.sample().drive_enabled, False)

    def test_explicit_gate_and_all_six_pwm_pads(self):
        data = {
            GPIO1_BASE+0x800: 1,
            GPIO1_BASE+0x12C0: GATE_EN,
            GPIO1_BASE+0x1280: GATE_EN
        }
        for pin, func in MCPWM4_ROUTES:
            data[PINCM_BASE+4*pin] = 0x80 | func
        read = lambda addr: data.get(addr, 0)
        self.assertTrue(gate_and_pads_connected(
            read, gate_active_level=1))
        self.assertFalse(gate_and_pads_connected(
            read, gate_active_level=0))
        data[PINCM_BASE+4*25] = 0
        self.assertFalse(gate_and_pads_connected(
            read, gate_active_level=1))
        with self.assertRaises(ValueError):
            gate_and_pads_connected(read, gate_active_level=2)

    def test_invalid_observer_cannot_inject_motor_drive(self):
        data = {OBS_BASE: 0x7, OBS_BASE+8: 100, OBS_BASE+0x14: 0}
        with self.assertRaisesRegex(ValueError, "not running/valid"):
            PWMObservation.from_qemu(lambda addr: data.get(addr, 0))
        m = VirtualBLDC(parameters())
        with self.assertRaises(ValueError):
            update_from_mcpwm(m, lambda addr: data.get(addr, 0),
                              gate_enabled=True)
        self.assertEqual(m.sample().mechanical_rpm, 0.0)


if __name__ == "__main__":
    unittest.main()
