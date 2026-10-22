#!/usr/bin/env python3
import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_pwm_deadband_diagnostic import native_deadband_source_clamp

class TestDeadband(unittest.TestCase):
    def test_previous_genuine_step_snapshots(self):
        for aq,compare,source in (([0,0,0,2,18,0],3,2),([18,0,0,2,0,0],9,0)):
            s=native_deadband_source_clamp(aq,[compare]*6,[1,1,1,512,1,1],red_ticks=32,fed_ticks=1,fed_enabled=True)
            self.assertEqual(s.source_phases,(source,))
            self.assertTrue(s.all_source_pwm_clamped)
            self.assertEqual(s.min_compare_ticks,31)
        self.assertEqual(s.reason,'ORIGINAL_SOURCE_PWM_CLAMPED_BELOW_DEADBAND')
    def test_source_above_deadband_is_not_suppressed(self):
        s=native_deadband_source_clamp([18,0,0,2,0,0],[40]*6,[18,1,1,512,1,1],red_ticks=32,fed_ticks=1,fed_enabled=True)
        self.assertFalse(s.all_source_pwm_clamped)
        self.assertTrue(s.source_active_pwm_present)
    def test_single_low_sink_is_not_source(self):
        s=native_deadband_source_clamp([0,0,0,2,0,0],[40]*6,[1,1,1,512,1,1],red_ticks=32,fed_ticks=1,fed_enabled=True)
        self.assertFalse(s.all_source_pwm_clamped)
        self.assertFalse(s.source_active_pwm_present)
    def test_fail_closed(self):
        with self.assertRaises(ValueError):
            native_deadband_source_clamp([18,0,0,2,0,0],[9]*6,[1]*6,red_ticks=1,fed_ticks=4,fed_enabled=True)

if __name__=='__main__':unittest.main(verbosity=2)
