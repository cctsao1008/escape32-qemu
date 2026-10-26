#!/usr/bin/env python3
"""E62 external Flight Controller must not await Original Guest readiness."""
import inspect
import unittest

from e62_autonomous_native_motor_probe import (
    _continuous_dshot_stages, _configure_autonomous_dshot, run
)


class ContinuousIndependentDShotTests(unittest.TestCase):
    def test_neutral_ramp_hold_neutral_all_have_positive_durations(self):
        stages = _continuous_dshot_stages(
            neutral_ms=1500, ramp_ms=1000, hold_ms=300,
            coast_ms=200, drive_permille=200, ramp_update_ms=5)
        self.assertEqual(stages, [
            (1500,0,0,1), (1000,0,200,5),
            (300,200,200,1), (200,0,0,1)])
        self.assertEqual(sum(stage[0] for stage in stages),3000)

    def test_interpolation_is_exact_in_fixture_native_integer_units(self):
        for kw in [
            dict(neutral_ms=1500,ramp_ms=1000,hold_ms=300,
                 coast_ms=200,drive_permille=201,ramp_update_ms=5),
            dict(neutral_ms=1500,ramp_ms=999,hold_ms=300,
                 coast_ms=200,drive_permille=200,ramp_update_ms=5),
        ]:
            with self.assertRaises(ValueError):
                _continuous_dshot_stages(**kw)

    def test_neutral_starts_with_real_dshot_zero_not_low_active_48(self):
        stages=_continuous_dshot_stages(
            neutral_ms=1500,ramp_ms=1000,hold_ms=300,
            coast_ms=200,drive_permille=200,ramp_update_ms=5)
        self.assertEqual(stages[0][1:3],(0,0))
        self.assertEqual(stages[-1][1:3],(0,0))

    def test_guest_ready_never_gates_external_frame_start(self):
        source=inspect.getsource(run)
        self.assertNotIn("_wait_for_original_receiver_ready",source)
        self.assertNotIn('evidence["receiver_ready"]',source)
        self.assertIn("_configure_autonomous_dshot",source)
        self.assertIn('"initial_receiver_diagnostic_only"',source)

    def test_config_does_not_require_guest_cpu_or_dma_parameters(self):
        params=inspect.signature(_configure_autonomous_dshot).parameters
        self.assertNotIn("guest_state",params)
        self.assertNotIn("guest_ready",params)
        self.assertNotIn("dma_ready",params)


if __name__=="__main__":
    unittest.main(verbosity=2)
