#!/usr/bin/env python3
"""P1 original-source throttle/OC/BEMF audit negative controls."""
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.native_p1_qualification import analyze,dshot_value


def example():
    stages=[(20,0,0,1),(20,200,200,1),(20,0,0,1)]
    sha="b"*64
    meta={"sha256":sha,
          "original_elf_sha256":"05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"}
    events=[]
    for i in range(60):
        stage=0 if i<20 else 1 if i<40 else 2
        value=0 if stage!=1 else dshot_value(200)
        events.append({"seq":len(events)+1,"vns":i*1000000,
                       "kind":"DSHOT","data":(i,stage,value,0,0,0)})
        if i in (25,30,35,40,45):
            rpm=150 if i==25 else 180 if i==30 else 200 if i==35 else 50 if i==40 else 0
            for k,data in (
                ("ROTOR",(rpm*1000,i*100,0,0,0,0)),
                ("BEMF_FRONTEND",(2047,2048,2049,1,2048,1)),
                ("OC_FRONTEND",(1000,1000,1000,7,7,0))):
                events.append({"seq":len(events)+1,"vns":i*1000000+100,
                               "kind":k,"data":data})
    events.append({"seq":len(events)+1,"vns":45000100,
                   "kind":"CMP_FILTER","data":(1,1,2048,2047,0,0)})
    evidence={
      "original_elf_sha256":meta["original_elf_sha256"],
      "native_dshot_scenario":{"sha256":sha},
      "host_guest_register_writes":False,
      "used_guest_wfi_or_gdb":False,
      "synthetic_timed_bemf_enabled":False,
      "configured_dshot_frames":60,
      "autonomous_dshot":{"sent":60,"elapsed_ns":60000000},
      "native_motor":{"model_fault":0,"ost3_latch_activations":0,
                      "native_1us_physics_ticks":50000},
      "qemu_run_wall_elapsed_s":2.0,
      "qemu_log_bytes":2048,
    }
    return events,evidence,stages,meta


class P1QualificationTest(unittest.TestCase):
    def test_mapping_uses_expected_ties_even(self):
        self.assertEqual(dshot_value(0),0)
        self.assertEqual(dshot_value(1000),2047)
        self.assertEqual(dshot_value(200),448)

    def test_good_virtual_fc_and_frontends(self):
        args=example()
        r=analyze(*args)
        self.assertTrue(r["qualified"],r["unwaived_observability_failures"])
        self.assertEqual(r["first_observed_50rpm_delay_ms"],5.0001)
        self.assertEqual(r["performance"]["virtual_s"],.06)
        self.assertFalse(r["signal_loss_and_fault_recovery_qualified"])

    def test_early_missed_command_frame_is_rejected(self):
        args=list(example())
        args[0][1]["data"]=(99,0,0,0,0,0)
        d=analyze(*args)
        self.assertIn("DSHOT_VIRTUAL_CLOCK_OR_VALUE_MISMATCH",
                      d["unwaived_observability_failures"])

    def test_healthy_oc_cannot_be_inferred_with_missing_valid_flag(self):
        args=list(example())
        for e in args[0]:
            if e["kind"]=="OC_FRONTEND":
                e["data"]=(1000,1000,1000,0,0,0)
        d=analyze(*args)
        self.assertIn("OC_FRONTEND_NOT_VALID_READY_DURING_DRIVE",
                      d["unwaived_observability_failures"])

    def test_bad_source_sha_rejected(self):
        args=list(example())
        args[1]["native_dshot_scenario"]["sha256"]="0"*64
        d=analyze(*args)
        self.assertIn("EVIDENCE_SCENARIO_SHA_MISMATCH",
                      d["unwaived_observability_failures"])


if __name__=="__main__":
    unittest.main(verbosity=2)
