#!/usr/bin/env python3
"""Script-first QEMU P1 case/matrix must fail closed; zero CLI dependency."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools.e62_native_scripted_test import decide,run_case,CASES
from tools.native_dshot_scenario import load_native_scenario


class P1ScriptedTest(unittest.TestCase):
    def test_single_source_pinned_case_list(self):
        for name,p in CASES.items():
            stages,meta=load_native_scenario(p)
            self.assertEqual(meta["dshot_frames"],sum(x[0] for x in stages))
        self.assertEqual(set(CASES),{"smoke","gentle","steps"})

    def test_wiring_smoke_never_overrides_rotor_failure(self):
        verdict={"qualified":True,"status":"PASS_P1_SIM_ONLY_OBSERVABILITY"}
        self.assertTrue(decide(0,0,verdict))
        self.assertFalse(decide(1,0,verdict))
        self.assertFalse(decide(0,1,verdict))
        self.assertFalse(decide(0,0,{"qualified":False,
                 "status":"FAIL_P1_SIM_ONLY_OBSERVABILITY"}))
        self.assertFalse(decide(0,0,{"qualified":True,
                 "status":"PASS_NATIVE_AUTONOMOUS_WIRING_SMOKE"}))
        self.assertFalse(decide(0,0,{}))

    def test_missing_source_evidence_never_fakes_a_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            def fake_run(args,log_path,timeout):
                if "e62_autonomous_native_motor_probe.py" in " ".join(args):
                    log_path.write_text("Probe failed\n")
                    return 1,"ORIGINAL_QEMU_FAIL"
                log_path.write_text("Missing event source\n")
                return 1,"TRACE_UNAVAILABLE"
            with patch("tools.e62_native_scripted_test.run_command",
                       side_effect=fake_run):
                result=run_case(
                    name="smoke",scenario=CASES["smoke"],
                    qemu=Path(temp)/"missing-qemu",elf=Path(temp)/"elf",
                    cfg=Path(temp)/"cfg",output=Path(temp),wall_timeout=60)
            self.assertFalse(result["qualified"])
            self.assertEqual(result["probe_exit_code"],1)
            self.assertEqual(result["analyzer_exit_code"],1)
            self.assertEqual(result["failures"],["NO_READABLE_VERDICT"])


if __name__=="__main__":
    unittest.main(verbosity=2)
