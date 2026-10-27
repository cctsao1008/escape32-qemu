#!/usr/bin/env python3
"""Do not confuse separate physical safety/CRC checks with loaded-motor recovery."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.ci.native_p1_fault_matrix import evaluate


def payload():
    cases={}
    for name,mask in (("nfault",0x20000),("oc-u",0x40000),
                      ("oc-v",0x40000),("oc-w",0x40000)):
        cases[name]={
            "fault":name,
            "irq_ipsr":44,
            "shutdown_pc":0x1234,
            "shutdown_pc_hit":0x1234,
            "tzflags":mask,
            "interrupt_flags":4,
            "gate_inactive":True
        }
    frame=((1000<<1)<<4)
    payload=frame>>4
    crc=(payload^(payload>>4)^(payload>>8))&15
    good_frame=frame|crc
    def record(value,ret,feed,after):
        return {"frame":value,"guest_frame":value,
                "delivered":32,"capture":32,"dma_beats":32,
                "callback_return":ret,
                "throttle_pre_callback":0,
                "throttle_after_callback":after,
                "watchdog_valid_feeds_delta":feed,
                "gate_output_inactive_after_callback":True,
                "ipsr":0}
    return cases,[record(good_frame,1,1,10)],[record(good_frame^1,0,0,0)]


class NativeP1FaultMatrix(unittest.TestCase):
    def test_independent_hardware_positives_do_not_claim_loaded_recovery(self):
        d=evaluate(*payload())
        self.assertTrue(d["qualified"],d["issues"])
        self.assertFalse(d["native_no_wfi_motor_under_load_fault_recovery"])
        self.assertFalse(d["dshot_signal_loss_timeout_and_fresh_rearm"])

    def test_missing_oc_phase_not_qualified(self):
        a,b,c=payload()
        del a["oc-v"]
        d=evaluate(a,b,c)
        self.assertFalse(d["qualified"])
        self.assertTrue(any("oc-v:" in x for x in d["issues"]))

    def test_bad_crc_wrongly_accepted_fails_closed(self):
        a,b,c=payload()
        c[0]["watchdog_valid_feeds_delta"]=1
        d=evaluate(a,b,c)
        self.assertFalse(d["qualified"])
        self.assertTrue(any("bad_dshot_crc:" in x for x in d["issues"]))


if __name__=="__main__":
    unittest.main(verbosity=2)
