#!/usr/bin/env python3
"""Contract tests for diagnostic preboot FC setup and passive source reads."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_preboot_fc_source import (
    SMOKE, validate_scenario, passive_until_final_frame,
)

ROOT = Path(__file__).resolve().parents[1]

class FakeQEMU:
    returncode = None
    def poll(self):
        return None

class PrebootFCTest(unittest.TestCase):
    def test_pin_same_original_p0_smoke(self):
        result = validate_scenario(ROOT / "scenarios/e62-native-p0-smoke.json")
        self.assertEqual(result["stages"], SMOKE)
        self.assertEqual(result["dshot_frames"], 3000)

    def test_reject_any_edited_scenario(self):
        import json
        original = json.loads(
            (ROOT / "scenarios/e62-native-p0-smoke.json").read_text())
        original["stages"][1]["duration_ms"] = 900
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"changed.json"
            path.write_text(json.dumps(original))
            with self.assertRaises(ValueError):
                validate_scenario(path)

    def test_passive_full_physical_fc_source_sequence(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"qemu.log"
            with path.open("w") as f:
                for i in range(3000):
                    f.write(f"E62_P0_EVENT seq={i+1} vns={i*1000000+100} "
                            f"kind=DSHOT a={i} b=0 c=0 d=0 e=0 f=0\n")
            self.assertEqual(passive_until_final_frame(
                path, FakeQEMU(), wall_timeout_s=1), 3000)

    def test_passive_rejects_missing_frame(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"qemu.log"
            path.write_text(
                "E62_P0_EVENT seq=1 vns=100 kind=DSHOT a=0 b=0 c=0 d=0 e=0 f=0\n"
                "E62_P0_EVENT seq=2 vns=200 kind=DSHOT a=2 b=0 c=0 d=0 e=0 f=0\n")
            with self.assertRaisesRegex(ValueError, "expected 1 got 2"):
                passive_until_final_frame(path, FakeQEMU(), wall_timeout_s=1)

    def test_machine_default_off_and_original_plant_untouched(self):
        source = (ROOT/"machine/am13e23019.c").read_text()
        fixture = (ROOT/"machine/am13e_autonomous_sitl.inc").read_text()
        self.assertIn('esc-sim-differential-fc-smoke',source)
        self.assertIn("if (s->esc_sim_differential_fc_smoke)",source)
        self.assertIn("am13e_auto_arm_differential_smoke",fixture)
        for ms,a,b,up in SMOKE:
            self.assertIn(f"{{{ms}U, {a}U, {b}U, {up}U}}",fixture)
        self.assertNotIn("esc_sim_differential_fc_smoke=true",source)

if __name__ == "__main__":
    unittest.main(verbosity=2)
