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
    # Fixture reproduces source Guest-completed physical CAP1/TIMG12
    # W1C acknowledgments and six-pad sector transitions. This is only
    # unit-test data, never injected into QEMU or a qualifying SITL run.
    for idx in range(22,35):
        for kind in ("PWM_PAIR","CAP1_ACK","TIMG12_ACK"):
            events.append({"seq":len(events)+1,
                           "vns":idx*1000000+200,
                           "kind":kind,
                           "data":(0,0,0,0,0,0)})
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
        self.assertTrue(r["dshot_from_second_frame_bounded_1khz"])
        self.assertEqual(r["dshot_max_observed_dispatch_error_ns"],0)
        self.assertEqual(r["source_guest_cap1_w1c_ack"],13)
        self.assertEqual(r["significant_rotor_direction_changes"],0)
        self.assertEqual(len(r["scenario_stage_motor_dynamics"]),3)
        self.assertEqual(r["scenario_stage_motor_dynamics"][1]["duration_ms"],20)
        self.assertFalse(r["signal_loss_and_fault_recovery_qualified"])

    def test_interactive_live_override_cannot_pass_scenario_json(self):
        args=list(example())
        args[0].append({"seq":len(args[0])+1,
                        "vns":50000000,"kind":"THROT_SET",
                        "data":(50,1,100,1,0,0)})
        r=analyze(*args)
        self.assertIn("MANUAL_LIVE_THROTTLE_NOT_REPRODUCIBLE_JSON_CASE",
                      r["unwaived_observability_failures"])

    def test_first_qemu_timer_dispatch_lateness_not_period_drift(self):
        args=list(example())
        # First QEMU TB can dispatch initial PA26 callback late; source
        # uses absolute 1ms deadlines thereafter. Do not classify that
        # 150us startup latency as a defective DShot flight controller.
        args[0][0]["vns"]=150000
        result=analyze(*args)
        self.assertTrue(result["qualified"],result["unwaived_observability_failures"])
        self.assertEqual(result["dshot_first_callback_lateness_ns"],150000)

    def test_two_ns_qemu_dispatch_quantization_is_accepted(self):
        args=list(example())
        args[0][10]["vns"]+=2
        r=analyze(*args)
        self.assertTrue(r["qualified"],r["unwaived_observability_failures"])
        self.assertEqual(r["dshot_max_observed_dispatch_error_ns"],2)
        self.assertEqual(r["dshot_steady_frames_nonzero_dispatch_ns"],1)

    def test_late_steady_frame_and_first_frame_overlap_are_rejected(self):
        args=list(example())
        args[0][10]["vns"]+=101
        result=analyze(*args)
        self.assertEqual(result["dshot_first_mismatch"]["frame_index"],10)
        self.assertIn("DSHOT_VIRTUAL_CLOCK_OR_VALUE_MISMATCH",
                      result["unwaived_observability_failures"])
        args=list(example())
        args[0][0]["vns"]=999999
        result=analyze(*args)
        self.assertEqual(result["dshot_first_mismatch"]["frame_index"],0)
        self.assertIn("DSHOT_VIRTUAL_CLOCK_OR_VALUE_MISMATCH",
                      result["unwaived_observability_failures"])

    def test_physical_original_guest_irq_acks_required(self):
        args=list(example())
        args[0][:]=[e for e in args[0] if e["kind"] not in (
            "CAP1_ACK","TIMG12_ACK")]
        result=analyze(*args)
        self.assertIn("INSUFFICIENT_ORIGINAL_GUEST_CLOSED_LOOP_AFTER_ARM",
                      result["unwaived_observability_failures"])

    def test_direction_reversal_is_a_real_separate_failure(self):
        args=list(example())
        rotor=[e for e in args[0] if e["kind"]=="ROTOR"]
        rotor[1]["data"]=(-200000,0,0,0,0,0)
        result=analyze(*args)
        self.assertIn("STARTUP_SIGNIFICANT_DIRECTION_REVERSAL",
                      result["unwaived_observability_failures"])
        self.assertEqual(result["significant_rotor_direction_changes"],2)

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
