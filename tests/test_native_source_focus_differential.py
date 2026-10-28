#!/usr/bin/env python3
"""OFF/OFF must reproduce before OFF/ON instrumentation attribution."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_source_focus_differential import compare, evaluate, ELF

def event(seq, ns, kind="DSHOT", data=None):
    return {"seq": seq, "vns": ns, "kind": kind,
            "data": list(data if data is not None else (seq-1,0,0,0,0,0))}

def meta(focus=None):
    return {"original_elf_sha256": ELF, "host_guest_register_writes": False,
            "used_guest_wfi_or_gdb": False, "source_focus_guest_or_motor_control": False,
            "motor_mode": "QEMU_VIRTUAL_CLOCK_NATIVE_ECX87_KV147_SIM_ONLY",
            "configured_dshot_frames": 3000, "source_focus_window_ms": focus}

def energy(delta=1, focus=False):
    return {"energy_delta_j": {"bus":delta}, "focused_switching_source_events":
            ([{"seq":i} for i in range(12)] if focus else []),
            "motor_p1_stability_qualified":False, "late_full_switch_events":0}

BASE=[event(1,100),event(2,1000100),event(3,2000100)]

class SourceFocusDifferentialTests(unittest.TestCase):
    def test_first_virtual_time_difference_is_never_normalized(self):
        other=[event(1,600),event(2,1000600),event(3,2000600)]
        result=compare(BASE,other)
        self.assertFalse(result["equal"])
        self.assertEqual(result["first_difference"][0],0)
        self.assertEqual(result["first_dshot_left_ns"],100)
    def test_aa_mismatch_blocks_ab_claim(self):
        other=[event(1,600),event(2,1000600),event(3,2000600)]
        result=evaluate((meta(),BASE),(meta(),other),None,
                        energy(),energy(),None,"baseline")
        self.assertEqual(result["classification"],"FAIL_BASELINE_NONREPRODUCIBLE")
        self.assertEqual(result["observer_non_intrusiveness"],"NOT_ESTABLISHED")
        self.assertFalse(result["motor_p1_stability_qualified"])
    def test_energy_difference_blocks_ab_claim(self):
        result=evaluate((meta(),BASE),(meta(),BASE),None,
                        energy(1),energy(2),None,"baseline")
        self.assertEqual(result["classification"],"FAIL_BASELINE_NONREPRODUCIBLE")
    def test_aa_match_not_observer_pass(self):
        result=evaluate((meta(),BASE),(meta(),BASE),None,
                        energy(),energy(),None,"baseline")
        self.assertEqual(result["classification"],"PASS_BASELINE_REPEATABILITY")
        self.assertEqual(result["observer_non_intrusiveness"],"NOT_YET_EVALUATED")
    def test_ab_requires_original_source_match(self):
        focus=[event(i+4,2_795_000_000+i*1000,"SWITCH_FOCUS",
                     [4,1,15,1,1,1]) for i in range(12)]
        changed=[event(1,101)]+BASE[1:]+focus
        result=evaluate((meta(),BASE),(meta(),BASE),
                        (meta("2795:2840"),changed),
                        energy(),energy(),energy(focus=True),"differential")
        self.assertEqual(result["classification"],"FAIL_OFF_ON_DIFFERENTIAL")
    def test_ab_pass_keeps_p1_unqualified(self):
        focus=[event(i+4,2_795_000_000+i*1000,"SWITCH_FOCUS",
                     [4,1,15,1,1,1]) for i in range(12)]
        result=evaluate((meta(),BASE),(meta(),BASE),
                        (meta("2795:2840"),BASE+focus),
                        energy(),energy(),energy(focus=True),"differential")
        self.assertEqual(result["classification"],"PASS_STRICT_SOURCE_FOCUS_DIFFERENTIAL")
        self.assertFalse(result["motor_p1_stability_qualified"])
    def test_ab_rejects_focus_limit(self):
        focus=[event(i+4,2_795_000_000+i*1000,"SWITCH_FOCUS",
                     [4,1,15,1,1,1]) for i in range(12)]
        focus.append(event(16,2_800_000_000,"SWITCH_FOCUS_LIMIT",[0]*6))
        result=evaluate((meta(),BASE),(meta(),BASE),
                        (meta("2795:2840"),BASE+focus),
                        energy(),energy(),energy(focus=True),"differential")
        self.assertEqual(result["classification"],"FAIL_INVALID_DIFFERENTIAL_EVIDENCE")

if __name__=="__main__":
    unittest.main()
