#!/usr/bin/env python3
"""G13B3D: host-only negative and timing/observation unit controls."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_g13b3_native_seed import fixture, plant
from tools.native_runtime_timeline import NativePwmTimeline
from tools.native_pwm_qualification import MCPWM4
from tools.virtual_bldc import OBS_BASE, GPIO1_BASE


class NativeRuntimeTimelineTests(unittest.TestCase):
    def setUp(self):
        self.hardware = fixture()
        self.motor = plant()
        self.timeline = NativePwmTimeline(self.motor)
        self.writes = []

    def observe(self, tick, label="native_wfi"):
        return self.timeline.observe(
            lambda addr: self.hardware.get(addr, 0),
            native_ticks=tick, checkpoint=label)

    def test_multiple_native_timestamps_advance_only_host_motor(self):
        self.observe(1000, "native_gate_return")
        for tick in (13500, 26000, 38500):
            self.observe(tick)
        result = self.timeline.require_progress()
        self.assertEqual(result["frames"], 4)
        self.assertEqual(result["integrated_intervals"], 3)
        self.assertEqual(result["native_elapsed_ns"], 187500)
        self.assertEqual(result["plant_integrated_ns"], 187500)
        self.assertFalse(result["feedback_injected"])
        self.assertTrue(any(abs(i) > 0 for i in self.motor.iabc))
        self.assertEqual(self.writes, [])

    def test_stop_local_pwm_snapshot_shared_with_audit_without_reread(self):
        reads = []
        def measured(addr):
            reads.append(addr)
            return self.hardware.get(addr, 0)
        a = self.timeline.observe(measured, native_ticks=1000,
                                  checkpoint="guest_wfi_1")
        image = self.timeline.last_observation
        self.assertIsNotNone(image)
        self.assertEqual(image.six_high_ticks, a.six_high_ticks)
        self.assertEqual(image.period_ticks, a.pwm_period_ticks)
        self.assertEqual(reads.count(OBS_BASE + 8), 1)
        self.hardware[OBS_BASE + 0x18] = 0
        b = self.timeline.observe(measured, native_ticks=13500,
                                  checkpoint="guest_wfi_2")
        self.assertEqual(b.six_high_ticks[0], 0)
        self.assertNotEqual(a.six_high_ticks, b.six_high_ticks)
        self.assertEqual(reads.count(OBS_BASE + 8), 2)

    def test_native_ecap_wrap_is_bounded_and_exact(self):
        self.observe(0xfffffff0, "native_gate_return")
        frame = self.observe(0x000030c0)
        self.assertEqual(frame.delta_ticks, 0x30d0)
        self.assertEqual(frame.interval_integrated_ns, 0x30d0 * 5)

    def test_decreasing_or_stalled_native_clock_is_rejected(self):
        self.observe(1000, "native_gate_return")
        for ticks in (1000, 999, 201001):
            with self.subTest(ticks=ticks):
                with self.assertRaisesRegex(ValueError, "time interval"):
                    self.observe(ticks)
        self.assertEqual(len(self.timeline.frames), 1)
        self.assertEqual(self.motor.sample().mechanical_rpm, 0)

    def test_native_pwm_change_detected_without_forged_integration(self):
        self.observe(1000, "native_gate_return")
        self.hardware[OBS_BASE + 0x24] = 4000
        changed = self.observe(13500)
        self.assertTrue(changed.pwm_image_changed)
        self.assertEqual(changed.qualifier, "PWM_CHANGE_UNRESOLVED_INTERVAL")
        self.assertEqual(changed.interval_integrated_ns, 0)
        self.assertEqual(self.motor.sample().mechanical_rpm, 0)
        self.observe(26000)
        self.assertEqual(self.timeline.integrated_intervals, 1)
        with self.assertRaisesRegex(AssertionError, "insufficient"):
            self.timeline.require_progress()

    def test_trip_gate_and_invalid_pwm_fail_without_plant_step(self):
        for address, value in (
                (MCPWM4 + 0xb0, 0x20000),
                (GPIO1_BASE + 0x1280, 0),
                (OBS_BASE + 0x14, 0)):
            with self.subTest(address=hex(address)):
                self.setUp()
                self.observe(1000, "native_gate_return")
                self.hardware[address] = value
                with self.assertRaisesRegex(ValueError, "native PWM"):
                    self.observe(13500)
                self.assertEqual(len(self.timeline.frames), 1)
                self.assertEqual(self.motor.sample().mechanical_rpm, 0)

    def test_invalid_configuration_or_timestamp(self):
        with self.assertRaises(ValueError):
            NativePwmTimeline(plant(), ecap_hz=199999999)
        with self.assertRaises(ValueError):
            NativePwmTimeline(plant(), max_delta_ticks=0)
        with self.assertRaises(ValueError):
            self.observe(-1)
        with self.assertRaises(ValueError):
            self.observe(1, label="")


if __name__ == "__main__":
    unittest.main(verbosity=2)
