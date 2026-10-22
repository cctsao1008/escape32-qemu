#!/usr/bin/env python3
"""G13B3E native BEMF injection: fail-closed host-only controls."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_g13b3_native_seed import fixture, plant, analog
from tools.native_runtime_timeline import NativePwmTimeline
from tools.native_bemf_injection import NativeBemfInjector
from tools.native_bemf_qualification import CMPSS0, ECAP1, SYS_HP_MUX, ECAP_POWER
from tools.native_pwm_qualification import MCPWM4
from tools.virtual_bldc import OBS_BASE
from tools.virtual_bldc_feedback import SIM_BEMF_INPUT, AnalogFrontend


def board():
    f = fixture()
    f[ECAP_POWER] = 0x610
    f[SYS_HP_MUX] = 0
    f[CMPSS0] = 0x8008
    f[CMPSS0 + 0x0c] = 2048 << 16
    f[ECAP1 + 0x24] = 45
    f[ECAP1 + 0x28] = 0x00900100
    f[ECAP1 + 0x2c] = 2
    return f


class NativeBemfInjectorTest(unittest.TestCase):
    def setUp(self):
        self.hardware = board()
        self.writes = []
        self.timeline = NativePwmTimeline(plant())
        self.injector = NativeBemfInjector(analog())

    def read(self, addr):
        return self.hardware.get(addr, 0)

    def write(self, addr, value):
        self.writes.append((addr, value))
        self.hardware[addr] = value

    def advance(self):
        for n in (1000, 13500, 26000, 38500):
            self.timeline.observe(self.read, native_ticks=n,
                                  checkpoint="native_gate_return" if n == 1000
                                  else "native_main_wfi")

    def inject(self, **kwargs):
        return self.injector.inject(
            self.timeline, self.read, self.write,
            selected_code=5, native_armed=True, **kwargs)

    def test_only_three_sim_inputs_and_plant_derived_codes(self):
        self.advance()
        record = self.inject()
        self.assertEqual(record.sample_index, 3)
        self.assertEqual([a for a, _ in self.writes],
                         [SIM_BEMF_INPUT + 4*i for i in range(3)])
        self.assertEqual(record.sample_words, analog().words(
            self.timeline.motor.sample(gate_enabled=True)))
        self.assertTrue(record.changed_from_neutral)

    def test_unarmed_route_trip_and_pwm_change_block_all_writes(self):
        for label in ("unarmed", "mux", "trip", "pwm"):
            with self.subTest(label=label):
                self.setUp()
                self.advance()
                if label == "unarmed":
                    armed = False
                else:
                    armed = True
                if label == "mux":
                    self.hardware[SYS_HP_MUX] = 2
                if label == "trip":
                    self.hardware[MCPWM4 + 0xb0] = 0x20000
                if label == "pwm":
                    self.hardware[OBS_BASE + 0x24] = 1
                with self.assertRaises(ValueError):
                    self.injector.inject(
                        self.timeline, self.read, self.write,
                        selected_code=5, native_armed=armed)
                self.assertEqual(self.writes, [])

    def test_saturation_does_not_modify_inputs(self):
        self.advance()
        injector = NativeBemfInjector(AnalogFrontend(
            reference_v=3.3, zero_bemf_bias_v=1.65,
            input_gain_v_per_bemf_v=10000))
        with self.assertRaisesRegex(ValueError, "saturated"):
            injector.inject(self.timeline, self.read, self.write,
                            selected_code=5, native_armed=True)
        self.assertEqual(self.writes, [])

    def test_requires_native_timestamp_and_multiple_nonzero_samples(self):
        with self.assertRaisesRegex(ValueError, "observation"):
            self.injector.inject(self.timeline, self.read, self.write,
                                 selected_code=5, native_armed=True)
        self.advance()
        self.inject()
        with self.assertRaises(AssertionError):
            self.injector.require_samples()


if __name__ == "__main__":
    unittest.main(verbosity=2)
