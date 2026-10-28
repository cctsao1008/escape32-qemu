#!/usr/bin/env python3
"""Fail-closed negative controls: Original Guest no-WFI external FC signal loss."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_p1_input_loss_audit import audit,WWDT_NS
from tools.native_dshot_scenario import SHA,load_native_scenario

SCENARIO=Path(__file__).resolve().parents[1]/"scenarios/e62-native-p1-input-loss.json"

def fixture():
    stages,meta=load_native_scenario(SCENARIO)
    events=[]
    seq=0
    for i in range(2800):
        ts=1_000_000_000+i*1_000_000
        seq+=1
        events.append({"seq":seq,"kind":"DSHOT","vns":ts,
                       "data":(i,1,0 if i<1500 else 448,0,0,0)})
        if i>1500:
            seq+=1
            events.append({"seq":seq,"kind":"WWDT_FEED","vns":ts+50000,
                           "data":(i-1500,0x30,0,0,0,0)})
    last_feed=events[-1]["vns"]
    run={"original_elf_sha256":SHA,"used_guest_wfi_or_gdb":False,
         "host_guest_register_writes":False,
         "synthetic_timed_bemf_enabled":False,
         "link_loss_guest_writes":False,
         "link_loss_original_firmware_unchanged":True,
         "status":"OBSERVED_P1_GUEST_WWDT_INPUT_LOSS_SIM_ONLY",
         "link_loss_last_frame":2800,"link_loss_last_dshot":448,
         "link_loss_wwdt_running_on_disconnect":True,
         "link_loss_bootrst_observed":True,
         "configured_dshot_frames":2800,
         "autonomous_dshot":{"sent":2800,"target_frames":2800,
                             "last_dshot":448},
         "original_guest_after":{"valid_frame_feeds":1299}}
    log=("ESC_SIM_WWDT_BOOTRST_REQUESTED: vns="+str(last_feed+WWDT_NS)+
         " source-owned input watchdog expired; PB13 LOW; "
         "PWM frozen; resetcause=0x0e")
    return events,run,log,stages

class OriginalGuestInputLossTests(unittest.TestCase):
    def test_exact_real_source_and_wwdt_deadline(self):
        ev,run,log,s=fixture()
        result=audit(ev,run,log,s)
        self.assertEqual(result["status"],
            "PASS_P1_NATIVE_GUEST_INPUT_LOSS_WWDT_BOOTRST_SIM_ONLY")
        self.assertEqual(result["external_dshot_frames"],2800)
        self.assertEqual(result["model_wwdt_deadline_error_ns"],0)
        self.assertFalse(result["input_loss_silicon_qualified"])
    def test_not_halted_guest(self):
        ev,run,log,s=fixture();run["used_guest_wfi_or_gdb"]=True
        result=audit(ev,run,log,s)
        self.assertIn("HOST_INTERVENED_WITH_GUEST_OR_SYNTHETIC_MOTOR",
                      result["issues"])
    def test_requires_accepted_wdt_source_write(self):
        ev,run,log,s=fixture()
        ev=[x for x in ev if x["kind"]!="WWDT_FEED"]
        result=audit(ev,run,log,s)
        self.assertIn("NO_GENUINE_GUEST_WWDT_FEED_MMIO",result["issues"])
    def test_wrong_hardware_model_virtual_timeout_rejected(self):
        ev,run,log,s=fixture()
        log=log.replace("vns="+str(ev[-1]["vns"]+WWDT_NS),
                        "vns="+str(ev[-1]["vns"]+WWDT_NS+10_000))
        result=audit(ev,run,log,s)
        self.assertIn("GUEST_WWDT_EXPIRY_NOT_ONE_SECOND_AFTER_LAST_FEED",
                      result["issues"])
    def test_source_not_stopped_exactly_at_active_last_frame(self):
        ev,run,log,s=fixture()
        run["link_loss_last_frame"]=2801
        result=audit(ev,run,log,s)
        self.assertIn("NO_PRECISE_EXTERNAL_FC_STOP_FRAME",result["issues"])
    def test_wwdt_config_not_artificial_short_period(self):
        ev,run,log,s=fixture()
        for item in ev:
            if item["kind"]=="WWDT_FEED":
                item["data"]=(item["data"][0],0x70,0,0,0,0)
                break
        result=audit(ev,run,log,s)
        self.assertIn("WWDT0_ORIGINAL_POLICY_NOT_NOMINAL_ONE_SECOND",
                      result["issues"])
    def test_gate_safe_off_before_reset_is_mandatory(self):
        ev,run,log,s=fixture()
        result=audit(ev,run,log.replace("PWM frozen","PWM unknown"),s)
        self.assertIn("NO_NATIVE_POWER_GATE_SAFE_OFF_BEFORE_RESET",
                      result["issues"])
    def test_no_duplicate_or_missing_external_frames(self):
        ev,run,log,s=fixture()
        ev=[x for x in ev if not
            (x["kind"]=="DSHOT" and x["data"][0]==500)]
        result=audit(ev,run,log,s)
        self.assertIn("EXTERNAL_DSHOT_SOURCE_NOT_EXACTLY_CUTOFF",
                      result["issues"])

if __name__=="__main__":
    unittest.main(verbosity=2)
