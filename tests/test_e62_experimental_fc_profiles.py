#!/usr/bin/env python3
"""Independent exact stage-word oracle for E62 SIM_ONLY preboot FC matrix.

No Guest motor writes, no fake CAP1, and no qualification of candidate
firmware as the immutable Original Rel17.3. Compare static QEMU source
stages against the FIVE existing scenario JSON artifacts, so the
experimental test cannot silently change a command profile.
"""
import json
import re
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"machine/am13e_autonomous_sitl.inc"
PROFILE_JSON={
    "smoke":"scenarios/e62-native-p0-smoke.json",
    "gentle":"scenarios/e62-native-p0-gentle.json",
    "steps":"scenarios/e62-native-p0-steps.json",
    "ramp100":"scenarios/e62-native-p1-ramp20-100ms.json",
    "ramp500":"scenarios/e62-native-p1-ramp20-500ms.json",
}
PINNED="05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"


class E62ExperimentalFCProfiles(unittest.TestCase):
    def test_preboot_profile_matches_original_scenario_exactly(self):
        src=SOURCE.read_text()
        for profile,path in PROFILE_JSON.items():
            with self.subTest(profile=profile):
                scenario=json.loads((ROOT/path).read_text())
                self.assertEqual(scenario["target_elf_sha256"],PINNED)
                self.assertEqual(scenario["frame_period_ns"],1_000_000)
                self.assertFalse(scenario["guest_ready_gating"])
                self.assertEqual(scenario["protocol"],"DSHOT600")
                expected=[]
                for stage in scenario["stages"]:
                    if stage["kind"]=="hold":
                        duration=stage["duration_ms"]
                        v=stage["permille"]
                        expected.append((duration,v,v,1))
                    elif stage["kind"]=="ramp":
                        expected.append((stage["duration_ms"],
                                         stage["from_permille"],
                                         stage["to_permille"],
                                         stage["update_ms"]))
                    else:
                        self.fail("Unsupported FC stage, fail closed")
                match=re.search(
                    r"static const AM13EAutoStage\s+"+re.escape(profile)+
                    r"\[\]\s*=\s*\{(?P<stages>.*?)\};",
                    src, re.DOTALL)
                self.assertIsNotNone(match,"QEMU profile missing: "+profile)
                observed=[tuple(map(int,words)) for words in
                    re.findall(r"\{\s*(\d+)U\s*,\s*(\d+)U\s*,\s*(\d+)U\s*,\s*(\d+)U\s*\}",
                               match.group("stages"))]
                self.assertEqual(observed,expected)
                self.assertEqual(sum(x[0] for x in observed),
                                 sum(x["duration_ms"] for x in scenario["stages"]))
                self.assertGreater(sum(x[0] for x in observed[1:]),1000)

    def test_only_explicit_allowed_profiles_and_no_guest_motor_writes(self):
        src=SOURCE.read_text()
        machine=(ROOT/"machine/am13e23019.c").read_text()
        self.assertIn("am13e_auto_arm_experimental_profile(",machine)
        self.assertIn("esc-sim-experimental-fc-profile",machine)
        for profile in PROFILE_JSON:
            self.assertIn('!strcmp(profile, "'+profile+'")',src)
            self.assertIn('strcmp(value,"'+profile+'")',machine)
        self.assertIn('a->start_ns = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 100U',src)
        self.assertIn('a->target_frames != a->total_frames',src)
        self.assertIn('esc_sim_experimental_fc_direct20 &&',machine)
        self.assertIn('s->esc_sim_experimental_fc_profile',machine)


if __name__=="__main__":
    unittest.main(verbosity=2)
