#!/usr/bin/env python3
"""G13B3A read-only original PWM physical qualification negative controls."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.virtual_bldc import (
    OBS_BASE, GATE_EN, GPIO1_BASE, PINCM_BASE, MCPWM4_ROUTES
)
from tools.native_pwm_qualification import (
    MCPWM4, SYSCTL_PERCLKCR, SYSCTL_PWREN, observe_original_pwm
)


def fixture():
    state = {
        GPIO1_BASE + 0x800: 1,
        GPIO1_BASE + 0x12c0: GATE_EN,
        GPIO1_BASE + 0x1280: GATE_EN,
        PINCM_BASE + 4*45: 0x81,
        SYSCTL_PERCLKCR: 1,
        SYSCTL_PWREN: 0x200,
        MCPWM4 + 0xb0: 0,
        OBS_BASE: 9,
        OBS_BASE + 8: 100,
        OBS_BASE + 0x14: 0x3f
    }
    for pin, mux in MCPWM4_ROUTES:
        state[PINCM_BASE + 4*pin] = 0x80 | mux
    for i, value in enumerate((75, 0, 0, 75, 0, 0)):
        state[OBS_BASE + 0x18 + 4*i] = value
    return state


class NativePWMQualification(unittest.TestCase):
    def test_qualified_native_image_without_fabricated_duty(self):
        f = fixture()
        x = observe_original_pwm(lambda addr: f.get(addr, 0))
        self.assertTrue(x.acceptable_for_plant)
        self.assertTrue(x.native_pwm_valid)
        self.assertEqual(x.six_high_ticks, (75, 0, 0, 75, 0, 0))
        self.assertEqual(x.six_duties, (.75, 0, 0, .75, 0, 0))

    def test_each_pwm_observer_register_sampled_once_per_checkpoint(self):
        f = fixture()
        reads = {}
        def measured(addr):
            reads[addr] = reads.get(addr, 0) + 1
            return f.get(addr, 0)
        image = observe_original_pwm(measured)
        self.assertTrue(image.acceptable_for_plant)
        self.assertEqual(reads[OBS_BASE], 1)
        self.assertEqual(reads[OBS_BASE + 8], 1)
        self.assertEqual(reads[OBS_BASE + 0x14], 1)
        for i in range(6):
            self.assertEqual(reads[OBS_BASE + 0x18 + i*4], 1)
        # Every fresh call still reads new silicon/QEMU register values.
        f[OBS_BASE + 0x18] = 0
        second = observe_original_pwm(measured)
        self.assertTrue(second.nonzero_phase_voltage_command)
        self.assertEqual(second.six_high_ticks[0], 0)
        self.assertEqual(reads[OBS_BASE + 0x18], 2)

    def test_reject_physical_trip_even_with_valid_native_aq(self):
        for flag in (0x20000, 0x40000, 0x60000):
            f = fixture()
            f[MCPWM4 + 0xb0] = flag
            x = observe_original_pwm(lambda addr: f.get(addr, 0))
            self.assertFalse(x.acceptable_for_plant)
            self.assertIn("Trip", x.reason)

    def test_reject_unpowered_timer_clock_or_gate(self):
        for addr, val in (
            (SYSCTL_PWREN, 0),
            (SYSCTL_PERCLKCR, 0),
            (GPIO1_BASE + 0x800, 0),
            (GPIO1_BASE + 0x12c0, 0),
            (GPIO1_BASE + 0x1280, 0),
            (PINCM_BASE + 4*45, 0),
            (PINCM_BASE + 4*MCPWM4_ROUTES[4][0], 0)
        ):
            with self.subTest(address=hex(addr)):
                f = fixture()
                f[addr] = val
                self.assertFalse(observe_original_pwm(
                    lambda a: f.get(a, 0)).acceptable_for_plant)

    def test_reject_invalid_observer_and_no_differential_drive(self):
        f = fixture()
        f[OBS_BASE + 0x14] = 0x3e
        x = observe_original_pwm(lambda a: f.get(a, 0))
        self.assertFalse(x.native_pwm_valid)
        self.assertFalse(x.acceptable_for_plant)

        f = fixture()
        for i in range(6):
            f[OBS_BASE + 0x18 + i*4] = 0
        x = observe_original_pwm(lambda a: f.get(a, 0))
        self.assertTrue(x.native_pwm_valid)
        self.assertFalse(x.nonzero_phase_voltage_command)
        self.assertFalse(x.acceptable_for_plant)

    def test_reject_overlapping_original_high_low(self):
        f = fixture()
        f[OBS_BASE + 0x18] = 90
        f[OBS_BASE + 0x1c] = 75
        x = observe_original_pwm(lambda a: f.get(a, 0))
        self.assertTrue(x.native_pwm_valid)
        self.assertFalse(x.acceptable_for_plant)
        self.assertIn("overlapping", x.reason)

    def test_active_low_requires_matching_polarity(self):
        f = fixture()
        f[GPIO1_BASE + 0x1280] = 0
        self.assertFalse(observe_original_pwm(
            lambda a: f.get(a, 0), gate_active_level=1
        ).acceptable_for_plant)
        self.assertTrue(observe_original_pwm(
            lambda a: f.get(a, 0), gate_active_level=0
        ).acceptable_for_plant)

    def test_negative_invalid_polarity(self):
        with self.assertRaises(ValueError):
            observe_original_pwm(lambda a: 0, gate_active_level=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
