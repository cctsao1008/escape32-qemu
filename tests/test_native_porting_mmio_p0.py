#!/usr/bin/env python3
"""Strict archived P0 Guest MMIO data provenance and native timer tests."""
import copy
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_porting_mmio_p0 import audit
from tools.native_porting_mmio_chain import PINNED_ELF

def event(seq,t,kind,*d):
    return {"seq":seq,"vns":t,"kind":kind,
            "data":tuple(d)+(0,)*(6-len(d))}

def trace():
    return [
        event(1,100000,"PWM_PAIR",8,24,15),
        event(2,110000,"CAP1",1000000,0,3,34),
        event(3,110040,"CAP1_ACK",2,3,1000000,34),
        event(4,110080,"ECAP1_CAP1_READ",1000000,1000002,1,34),
        event(5,200000,"T12_LOAD",99999,100000000),
        event(6,200010,"T12_START",99999,100000000,99999,0,1),
        event(7,1200010,"TIMG12",1,1,99999),
        event(8,1200040,"TIMG12_ACK",1,1,1,99999),
    ]

def evidence():
    return {"original_elf_sha256":PINNED_ELF,"used_guest_wfi_or_gdb":False,
            "host_guest_register_writes":False,
            "synthetic_timed_bemf_enabled":False}

class TestPortingP0(unittest.TestCase):
    def test_strict_real_source_contract(self):
        o=audit(trace(),evidence())
        self.assertEqual(o["status"],"PASS_SOURCE_MMIO_P0_SIM_ONLY")
        self.assertEqual(o["matched_cap1_ack_guest_read"],1)
        self.assertEqual(o["matched_original_guest_timer_start_zero"],1)
        self.assertEqual(o["max_absolute_timer_deadline_error_ns"],0)
        self.assertFalse(o["hardware_qualified"])
        self.assertFalse(o["guest_internal_accepted_rejected_decision_directly_seen"])
    def test_wrong_timer_zero_fails(self):
        ev=copy.deepcopy(trace());ev[6]["vns"]+=500
        o=audit(ev,evidence())
        self.assertTrue(any("ZERO_DEADLINE_MISMATCH" in x for x in o["issues"]))
    def test_missing_guest_cap1_read_fails(self):
        ev=[x for x in trace() if x["kind"]!="ECAP1_CAP1_READ"]
        with self.assertRaisesRegex(ValueError,"missing source event ECAP1_CAP1_READ"):
            audit(ev,evidence())
    def test_guest_timer_without_start_fails(self):
        ev=[x for x in trace() if x["kind"]!="T12_START"]
        with self.assertRaisesRegex(ValueError,"missing source event T12_START"):
            audit(ev,evidence())
    def test_no_faked_guest_provenance(self):
        p=evidence();p["host_guest_register_writes"]=True
        with self.assertRaisesRegex(ValueError,"invalid source provenance"):
            audit(trace(),p)
    def test_stale_zero_after_stop_fails(self):
        ev=copy.deepcopy(trace())
        ev.insert(6,event(20,500000,"T12_STOP",50000,99999,0,0))
        o=audit(ev,evidence())
        self.assertTrue(any("ZERO_WITHOUT_ORIGINAL_GUEST_TIMER_START" in x
                            for x in o["issues"]))

if __name__=="__main__":
    unittest.main(verbosity=2)
