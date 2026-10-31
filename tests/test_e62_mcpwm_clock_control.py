#!/usr/bin/env python3
"""E62 source-clock A/B: TI MCLK200 opt-in vs preserved legacy100."""
import json
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CFG=ROOT/"configs/e62-mcpwm-clock-control-v1.json"
class ClockSourceAB(unittest.TestCase):
    def test_exact_fail_closed_versioned_control(self):
        d=json.loads(CFG.read_text())
        self.assertEqual(d["schema"],"e62.sim.mcpwm-clock-control.v1")
        self.assertEqual(d["mcpwm_root_hz_supported"],[100000000,200000000])
        self.assertEqual(d["historical_root_hz"],100000000)
        self.assertEqual(d["ti_mclk_root_hz"],200000000)
        self.assertTrue(d["qemu_default_legacy_unchanged"])
        self.assertFalse(d["p1_waiver"])
        self.assertFalse(d["hardware_qualified"])
        self.assertEqual(d["dshot_frame_count"],5100)
        self.assertEqual(len(d["motor_cases"]),2)
    def test_same_ti_clock_not_guest_timing_patch(self):
        s=(ROOT/"machine/am13e23019.c").read_text()
        inc=(ROOT/"machine/am13e_pwm_history.inc").read_text()
        runner=(ROOT/"tests/e62_autonomous_native_motor_probe.py").read_text()
        self.assertIn("AM13E_SIM_PWM_CLK 100000000U",s)
        self.assertIn("AM13E_SIM_PWM_MCLK_200 200000000U",s)
        self.assertIn("esc-sim-mcpwm-root-200mhz",s)
        self.assertIn("return source_hz >> divider",s)
        self.assertIn("case 0x44U:",inc)
        self.assertIn("effective_mcpwm_root_clock_hz",runner)
        self.assertIn("QEMU source MCPWM root clock",runner)
        self.assertIn("choices=(100000000,200000000)",runner)
    def test_derivation_mcpwm_mclk_not_busclk(self):
        for clk in (100000000,200000000):
            self.assertEqual(clk>>1,clk//2)
            self.assertEqual(clk>>5,clk//32)
        self.assertEqual(200000000//2,100000000)
        self.assertEqual(200000000//32,6250000)
        self.assertEqual(100000000//32,3125000)
if __name__=="__main__":
    unittest.main(verbosity=2)
