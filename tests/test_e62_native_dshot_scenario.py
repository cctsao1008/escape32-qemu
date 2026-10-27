#!/usr/bin/env python3
"""Native DShot JSON stage/ELF/clock boundaries fail-closed."""
import json, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_dshot_scenario import load_native_scenario, ScenarioError
ROOT=Path(__file__).resolve().parents[1]
SC=ROOT/"scenarios/e62-native-p0-smoke.json"


class TestNativeScenarios(unittest.TestCase):
    def test_presets(self):
        for fn,total in [("e62-native-p0-smoke.json",3000),
                         ("e62-native-p0-gentle.json",5000),
                         ("e62-native-p0-steps.json",3300)]:
            stages,info=load_native_scenario(ROOT/"scenarios"/fn)
            self.assertEqual(info["dshot_frames"],total)
            self.assertEqual(stages[0][1:3],(0,0))
            self.assertEqual(stages[-1][1:3],(0,0))
            self.assertFalse(info["guest_ready_gating"])

    def test_broken_scenarios_refused(self):
        doc=json.loads(SC.read_text())
        mutations=(
            lambda x:x.update(guest_ready_gating=True),
            lambda x:x.update(frame_period_ns=2000000),
            lambda x:x.update(target_elf_sha256="bad"),
            lambda x:x["stages"][0].update(permille=1),
            lambda x:x["stages"][-1].update(permille=1),
            lambda x:x["stages"][1].update(update_ms=7),
            lambda x:x["stages"][1].update(from_permille=10),
            lambda x:x["stages"][1].update(extra=0),
            lambda x:x.update(extra=0),
        )
        for mutate in mutations:
            d=json.loads(json.dumps(doc));mutate(d)
            with tempfile.TemporaryDirectory() as td:
                f=Path(td)/"invalid.json";f.write_text(json.dumps(d))
                with self.subTest(mutate=mutate), self.assertRaises(ScenarioError):
                    load_native_scenario(f)


if __name__=="__main__":
    unittest.main(verbosity=2)
