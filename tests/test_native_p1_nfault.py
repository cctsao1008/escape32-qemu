#!/usr/bin/env python3
"""Physical PA22 nFAULT native Guest flight-test negative controls."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.native_dshot_scenario import load_native_scenario
from tools.native_p1_fault_plan import FaultPlanError, load_fault_plan
from tools.native_p1_nfault_audit import audit


def fixture():
    frames=30
    plan={"assert_frame":10,"release_frame":20,"sha256":"f"*64}
    events=[]
    for i in range(frames):
        if i in (10,20):
            events.append({"seq":len(events)+1,"vns":i*1000000,
                           "kind":"NFAULT_EDGE",
                           "data":(1 if i==10 else 0,i,0x20000,4,0,0)})
        events.append({"seq":len(events)+1,"vns":i*1000000,
                       "kind":"DSHOT","data":(i,1,448,0,0,0)})
    evidence={
        "configured_dshot_frames":frames,
        "native_external_fault_plan":{"sha256":plan["sha256"]},
        "autonomous_dshot":{"sent":frames},
        "host_guest_register_writes":False,
        "used_guest_wfi_or_gdb":False,
        "synthetic_timed_bemf_enabled":False,
        "original_guest_after":{"valid_frame_feeds":15},
        "receiver_after":{"native_ost_latched":0x20000,
                          "native_pwm_trip_latch":0x20000},
        "native_motor":{"actual_pwm_six_bit_mask":0},
        "pwm_source_after":{"running":False}
    }
    return events,evidence,plan


class NativeFaultTests(unittest.TestCase):
    def test_versioned_fault_plan_drives_positive_throttle_only(self):
        stages,_=load_native_scenario(ROOT/"scenarios/e62-native-p0-smoke.json")
        plan=load_fault_plan(ROOT/"scenarios/e62-native-p1-nfault.json",stages)
        self.assertEqual((plan["assert_frame"],plan["release_frame"]), (2100,2300))
        base=json.loads((ROOT/"scenarios/e62-native-p1-nfault.json").read_text())
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"bad.json"
            base["assert_frame"]=100
            p.write_text(json.dumps(base))
            with self.assertRaises(FaultPlanError):
                load_fault_plan(p,stages)

    def test_physical_fault_trace_expected_safe_latch(self):
        r=audit(*fixture())
        self.assertTrue(r["qualified"],r["failures"])
        self.assertFalse(r["automatic_rearm_and_flight_recovery_qualified"])

    def test_after_fault_pwm_pair_or_missing_ost_fails(self):
        args=list(fixture())
        args[0].append({"seq":len(args[0])+1,"vns":25000000,
                        "kind":"PWM_PAIR","data":(2,1,15,0,0,0)})
        r=audit(*args)
        self.assertIn("MOTOR_COMMUTATION_CONTINUED_AFTER_PHYSICAL_TRIP",r["failures"])
        args=list(fixture())
        args[1]["receiver_after"]["native_pwm_trip_latch"]=0
        self.assertIn("PHYSICAL_FAULT_LATCH_NOT_PERSISTENT_AT_END",
                      audit(*args)["failures"])


if __name__=="__main__":
    unittest.main(verbosity=2)
