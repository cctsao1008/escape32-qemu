#!/usr/bin/env python3
"""Source-only DShot-neutral diagnostics: no inferred transitions or P1 waive."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_source_neutral_diagnostics import (
    ELF, FORMAT, WINDOW_NS, ObservationError, inspect_neutral_return
)

def document():
    def sample(t,rpm,torque,amps,mask=None):
        return {"t_ns":t,"motor_rpm":rpm,"torque_nm":torque,
                "phase_currents_a":amps,"bemf_codes":[2010,2048,2090],
                "pwm_six_pad_mask":mask}
    def event(seq,t,kind,raw):
        return {"seq":seq,"t_ns":t,"kind":kind,"data":[0,0,raw,0,0,0]}
    return {
        "format":FORMAT,"scope":"SIM_ONLY_NATIVE_NO_WFI_SOURCE_ONLY",
        "metadata":{"elf_sha256":ELF,"timebase":"QEMU_CLOCK_VIRTUAL"},
        "samples":[
            sample(90_000_000,400,0.1,[1,-1,0],18),
            sample(100_000_000,380,-0.25,[2,-2,0]),
            sample(101_000_000,220,-2.0,[11,-10,-1]),
            sample(110_000_000,40,-0.1,[0.5,-0.2,-0.3]),
            sample(135_000_000,5,0.0,[0,0,0]),
            sample(136_000_000,5,0.0,[0,0,0])],
        "events":[event(1,90_000_000,"DSHOT",448),
                  event(2,100_000_000,"DSHOT",0),
                  event(3,101_000_000,"CAP1",1),
                  event(4,102_000_000,"TIMG12",1),
                  event(5,105_000_000,"PWM_PAIR",3),
                  event(6,115_000_000,"DSHOT",0)]
    }

class Tests(unittest.TestCase):
    def test_exact_timestamp_and_observations(self):
        result=inspect_neutral_return(document())
        self.assertEqual(result["trigger"]["t_ns"],100_000_000)
        self.assertEqual(result["window"]["source_samples"],4)
        self.assertTrue(result["window"]["fully_covered"])
        self.assertEqual(result["rpm"]["first"],380)
        self.assertEqual(result["rpm"]["last"],5)
        self.assertEqual(result["torque"]["minimum_nm"],-2)
        self.assertEqual(result["phase_currents"]["maximum_sampled_absolute_a"],11)
        self.assertEqual(result["fresh_pwm_switch_masks_in_window"],0)
        self.assertEqual(result["source_events_in_window"]["CAP1"],1)
        self.assertFalse(result["motor_p1_stability_qualified"])
        self.assertIn("MECHANISM_UNDETERMINED",result["classification"])
    def test_no_neutral_transition_means_no_claim(self):
        doc=document()
        doc["events"][1]["data"][2]=448
        doc["events"][-1]["data"][2]=448
        with self.assertRaisesRegex(ObservationError,"No source-owned"):
            inspect_neutral_return(doc)
    def test_wrong_pin_rejected(self):
        doc=document();doc["metadata"]["elf_sha256"]="x"*64
        with self.assertRaisesRegex(ObservationError,"pinned"):
            inspect_neutral_return(doc)
    def test_unsorted_events_rejected(self):
        doc=document();doc["events"][3]["seq"]=3
        with self.assertRaisesRegex(ObservationError,"nonmonotonic"):
            inspect_neutral_return(doc)
    def test_partial_coverage_is_explicit(self):
        doc=document();doc["samples"]=doc["samples"][:4]
        report=inspect_neutral_return(doc)
        self.assertFalse(report["window"]["fully_covered"])
    def test_custom_window_budget(self):
        with self.assertRaisesRegex(ObservationError,"Focus window"):
            inspect_neutral_return(document(),window_ns=600_000_000)

if __name__=="__main__":
    unittest.main(verbosity=2)
