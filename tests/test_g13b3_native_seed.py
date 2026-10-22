#!/usr/bin/env python3
"""G13B3B: original PWM -> one simulated carrier plant-seed host-only tests."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.virtual_bldc import (
    OBS_BASE, GPIO1_BASE, PINCM_BASE, GATE_EN, MCPWM4_ROUTES,
    MotorParameters, VirtualBLDC,
)
from tools.virtual_bldc_feedback import AnalogFrontend
from tools.native_bldc_seed import one_native_pwm_period
from tools.native_pwm_qualification import (
    MCPWM4, SYSCTL_PERCLKCR, SYSCTL_PWREN
)


def fixture():
    state = {
        GPIO1_BASE + 0x800: 1,
        GPIO1_BASE + 0x12c0: GATE_EN,
        GPIO1_BASE + 0x1280: GATE_EN,
        PINCM_BASE + 4 * 45: 0x81,
        SYSCTL_PERCLKCR: 1,
        SYSCTL_PWREN: 0x200,
        MCPWM4 + 0xb0: 0,
        OBS_BASE: 15,
        OBS_BASE + 8: 6251,
        OBS_BASE + 0x14: 0x3f,
    }
    for pin, mux in MCPWM4_ROUTES:
        state[PINCM_BASE + 4 * pin] = 0x80 | mux
    for i, count in enumerate((0, 0, 0, 6220, 0, 0)):
        state[OBS_BASE + 0x18 + i * 4] = count
    return state


def plant():
    return VirtualBLDC(MotorParameters(
        vbus_v=24, phase_resistance_ohm=.3,
        phase_inductance_h=.002,
        bemf_constant_v_per_rad_s=.02,
        torque_constant_nm_per_a=.02,
        inertia_kg_m2=1e-6,
        viscous_friction_nm_per_rad_s=.0001,
        load_torque_nm=0, pole_pairs=7))


def analog():
    return AnalogFrontend(reference_v=3.3, zero_bemf_bias_v=1.65,
                          input_gain_v_per_bemf_v=.02)


class NativeMotorOnePeriod(unittest.TestCase):
    def test_native_vlow_single_carrier_yields_physical_test_motor(self):
        f = fixture()
        m = plant()
        sample = one_native_pwm_period(
            m, analog(), lambda addr: f.get(addr, 0),
            gate_active_level=1)
        self.assertEqual(sample.pwm_period_ns, 62510)
        self.assertEqual(sample.duties[3], 6220/6251)
        self.assertTrue(sample.motor.drive_enabled)
        self.assertGreater(sample.motor.mechanical_rpm, 0)
        self.assertTrue(any(abs(i) > 0 for i in sample.motor.phase_currents_a))
        self.assertTrue(all(0x10000 <= code <= 0x10fff
                            for code in sample.bemf_voltage_codes))
        self.assertEqual(
            len(sample.bemf_voltage_codes), 3)
        # No guest register/image writes required by this read-only path.
        self.assertEqual(f[OBS_BASE + 0x24], 6220)

    def test_reject_trip_before_any_motor_advance(self):
        f = fixture()
        f[MCPWM4 + 0xb0] = 0x20000
        m = plant()
        with self.assertRaisesRegex(ValueError, "Trip"):
            one_native_pwm_period(m, analog(), lambda addr: f.get(addr, 0),
                                  gate_active_level=1)
        self.assertEqual(m.sample().mechanical_rpm, 0)

    def test_reject_missing_gate_or_invalid_native_observer(self):
        for fault_addr, invalid in (
                (GPIO1_BASE + 0x12c0, 0),
                (OBS_BASE + 0x14, 0x1f),
                (SYSCTL_PERCLKCR, 0),
                (SYSCTL_PWREN, 0)):
            f = fixture()
            f[fault_addr] = invalid
            with self.assertRaises(ValueError):
                one_native_pwm_period(plant(), analog(),
                                      lambda addr: f.get(addr, 0),
                                      gate_active_level=1)

    def test_reject_unrepresented_pwm_clock(self):
        f = fixture()
        with self.assertRaisesRegex(ValueError, "representable"):
            one_native_pwm_period(
                plant(), analog(), lambda addr: f.get(addr, 0),
                gate_active_level=1, timer_hz=99999997)

    def test_reject_invalid_clock_and_no_differential_voltage(self):
        f = fixture()
        with self.assertRaisesRegex(ValueError, "timer rate"):
            one_native_pwm_period(plant(), analog(), lambda addr: f.get(addr, 0),
                                  gate_active_level=1, timer_hz=0)
        for i in range(6):
            f[OBS_BASE + 0x18 + 4*i] = 0
        with self.assertRaisesRegex(ValueError, "differential"):
            one_native_pwm_period(plant(), analog(), lambda addr: f.get(addr, 0),
                                  gate_active_level=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
