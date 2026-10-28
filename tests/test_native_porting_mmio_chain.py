#!/usr/bin/env python3
"""Fail-closed device-MMIO provenance tests. No synthetic Guest acceptance."""
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_p0_strict import parse_events
from tools.native_porting_mmio_chain import audit,timer_deadline_from_actual_start

def event(seq,t,kind,*data):
    return {"seq":seq,"vns":t,"kind":kind,
            "data":tuple(data)+(0,)*(6-len(data))}

def sample():
    # First CAP1 actually ACKed and read, but no following TIMER arm.
    # Second CAP1 is ACKed and read; true Guest loads a 2ms period,
    # STARTS the one-shot, HW ZERO fires and Guest ACKs.
    records=[
        event(1,1_000_000,"DSHOT",1,0,448),
        event(2,1_200_000,"PWM_PAIR",8,24,15),
        event(3,3_600_000,"CMP_FILTER",0,1),
        event(4,3_600_000,"CAP1",75500000,0,3,34),
        event(5,3_600_040,"CAP1_ACK",2,3,75500000,34),
        event(6,3_600_080,"ECAP1_CAP1_READ",75500000,75501000,1,34,144),
        event(7,11_900_000,"CMP_FILTER",0,1),
        event(8,11_900_000,"CAP1",77200000,0,3,34),
        event(9,11_900_040,"CAP1_ACK",2,3,77200000,34),
        event(10,11_900_080,"ECAP1_CAP1_READ",77200000,77201000,1,34,144),
        event(11,12_000_000,"T12_LOAD",199999,100000000,0,0),
        event(12,12_000_020,"T12_START",199999,100000000,199999,0,1),
        event(13,14_000_020,"TIMG12",1,1,199999),
        event(14,14_000_060,"TIMG12_ACK",1,1,1,199999),
        event(15,14_030_000,"PWM_PAIR",4,6,15),
    ]
    return records

def verdict():
    return {"status":"FAIL_P1_SIM_ONLY_OBSERVABILITY","qualified":False}

class SourceHardwareContract(unittest.TestCase):
    def test_first_capture_ack_read_not_equivalent_to_fw_acceptance(self):
        r=audit(sample(),verdict(),"direct20")
        self.assertEqual(r["status"],"PASS_MMIO_SOURCE_CONTRACT")
        self.assertTrue(r["first_cap1_did_not_observably_arm_timer"])
        self.assertTrue(r["first_then_second_capture_arm_pattern_observed"])
        self.assertEqual(r["timg12_virtual_deadline_error_ns"],0)
        self.assertFalse(r["p1_unchanged_qualified"])
        self.assertFalse(r["captured_before_first_timg12"][0][
                         "firmware_accept_reject_return_value_observed"])
    def test_qemu_virtual_timer_exact_ticks(self):
        e=event(1,12_000_020,"T12_START",199999,100000000,199999,0,1)
        self.assertEqual(timer_deadline_from_actual_start(e),
                         (14_000_020,200000))
    def test_wrong_guest_start_zero_delta_must_fail(self):
        rows=sample()
        rows[12]["vns"]+=200
        rows[13]["vns"]+=200
        rows[14]["vns"]+=200
        r=audit(rows,verdict(),"direct20")
        self.assertIn("NATIVE_TIMG12_ZERO_MISMATCHES_GUEST_ARMED_PERIOD",
                      r["issues"])
    def test_cap1_register_mismatch_not_marked_guest_read(self):
        rows=sample()
        rows[5]["data"]=(75500200,75501000,1,34,144,0)
        r=audit(rows,verdict(),"direct20")
        self.assertIn("CAP1_NO_MATCHING_GUEST_READ",r["issues"])
    def test_missing_timer_mmio_source_fails_closed(self):
        rows=[e for e in sample() if e["kind"]!="T12_START"]
        with self.assertRaisesRegex(ValueError,"missing original Guest TIMG12"):
            audit(rows,verdict(),"direct20")
    def test_parse_new_events_with_strict_global_clock_order(self):
        lines=[]
        for e in sample():
            a,b,c,d,f,g=e["data"]
            lines.append(f'E62_P0_EVENT seq={e["seq"]} vns={e["vns"]} '
                         f'kind={e["kind"]} a={a} b={b} c={c} '
                         f'd={d} e={f} f={g}')
        self.assertEqual(len(parse_events(lines)),len(lines))
        with self.assertRaisesRegex(ValueError,"Missing/reordered"):
            parse_events(lines[::-1])
    def test_existing_p0_p1_strict_thresholds_untouched(self):
        from tools.native_p0_strict import SIGNIFICANT_SPEED_RPM
        self.assertEqual(SIGNIFICANT_SPEED_RPM,50)
        source=(Path(__file__).resolve().parents[1]/
                "tools/native_p1_qualification.py").read_text()
        self.assertIn("STARTUP_SIGNIFICANT_DIRECTION_REVERSAL",source)
    def test_guest_probe_is_observer_not_actuator(self):
        root=Path(__file__).resolve().parents[1]
        machine=(root/"machine/am13e23019.c").read_text()
        fb=(root/"machine/am13e_motor_feedback.inc").read_text()
        for kind in ("T12_LOAD","T12_START","T12_STOP"):
            self.assertIn('am13e_p0_event(t->machine, "'+kind+'"',machine)
        self.assertIn('am13e_p0_event(f->machine, "ECAP1_CAP1_READ"',fb)
        self.assertIn('if (t->base == 0x40188000U',machine)

if __name__=="__main__":
    unittest.main(verbosity=2)
