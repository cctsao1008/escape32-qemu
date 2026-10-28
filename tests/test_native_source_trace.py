#!/usr/bin/env python3
"""Bounded No-WFI source-only adapter contract and false-source negative tests."""
import copy
import io
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_source_trace import (
    NativeSourceReducer, SourceTraceError, FORMAT, ELF,
    MAX_PENDING_EVENTS, convert, read_source_line,
)

def event(seq,vns,kind,*data):
    data=tuple(data)+(0,)*(6-len(data))
    return {"seq":seq,"vns":vns,"kind":kind,"data":list(data)}

def line(e):
    d=e["data"]
    return (f"qemu: E62_P0_EVENT seq={e['seq']} vns={e['vns']} "
            f"kind={e['kind']} a={d[0]} b={d[1]} c={d[2]} "
            f"d={d[3]} e={d[4]} f={d[5]}\n")

def fixture():
    return [
        event(1,100,"DSHOT",0,0,447),
        event(2,500,"SWITCH",18,1,1,0),
        event(3,1_000_000,"ROTOR",123456,100,2300,-700,-1600,44000),
        event(4,1_000_000,"BEMF_FRONTEND",2001,2012,2023,1,2048,1),
        event(5,1_200_000,"CAP1",1223,1,2,3),
        event(6,1_201_000,"ECAP1_CAP1_READ",1223,1225,0,3),
        event(7,1_300_000,"T12_START",50000,100000000,1),
        event(8,1_900_000,"TIMG12",1,1,50000),
        event(9,3_000_000,"ROTOR",-9876,200,-200,0,200,2000),
        event(10,3_000_000,"BEMF_FRONTEND",1800,1810,1820,0,2060,0),
    ]

class NativeSourceTest(unittest.TestCase):
    def test_real_source_semantics_not_inferred_voltage(self):
        r=NativeSourceReducer()
        frames=[r.ingest(x) for x in fixture()]
        samples=[f["sample"] for f in frames if f]
        self.assertEqual(len(samples),2)
        self.assertEqual(r.metadata["format"],FORMAT)
        self.assertEqual(r.metadata["elf_sha256"],ELF)
        self.assertEqual(samples[0]["motor_rpm"],123.456)
        self.assertEqual(samples[0]["phase_currents_a"],[2.3,-0.7,-1.6])
        self.assertEqual(samples[0]["torque_nm"],0.044)
        self.assertEqual(samples[0]["bemf_codes"],[2001,2012,2023])
        self.assertNotIn("bemf_phase_v",samples[0])
        self.assertEqual(samples[0]["pwm_six_pad_mask"],18)
        self.assertIsNone(samples[1]["pwm_six_pad_mask"])
        self.assertEqual(samples[1]["cap1_count"],1)
        self.assertEqual(samples[1]["timg12_count"],1)
        self.assertEqual(samples[1]["last_dshot_raw"],447)
        self.assertEqual(r.finish()["observed_samples"],2)
        self.assertFalse(r.finish()["hardware_qualified"])
    def test_offline_source_json_has_provenance_and_sequential_events(self):
        d=convert([line(x) for x in fixture()])
        self.assertEqual(d["format"],FORMAT)
        self.assertEqual(d["scope"],"SIM_ONLY_NATIVE_NO_WFI_SOURCE_ONLY")
        self.assertEqual(len(d["samples"]),2)
        self.assertTrue(all(d["events"][i]["seq"]<d["events"][i+1]["seq"]
                            for i in range(len(d["events"])-1)))
        self.assertEqual(d["native_result"],None)
        self.assertEqual(json.loads(json.dumps(d,allow_nan=False)),d)
    def test_not_a_malformed_qemu_event_or_false_line(self):
        self.assertIsNone(read_source_line("qemu harmless timer message\n"))
        self.assertEqual(read_source_line(line(fixture()[0]))["kind"],"DSHOT")
        with self.assertRaisesRegex(SourceTraceError,"Malformed"):
            read_source_line("E62_P0_EVENT seq=1 kind=ROTOR")
        with self.assertRaisesRegex(SourceTraceError,"Unknown"):
            read_source_line(line(event(1,0,"FAKE_GUEST_IRQ")))
    def test_missing_source_sequence_rejected(self):
        rows=fixture();rows[6]["seq"]=80
        with self.assertRaisesRegex(SourceTraceError,"Gap/time reversal"):
            convert([line(x) for x in rows])
    def test_opt_in_focus_is_real_source_and_sample_provenance(self):
        rows=fixture()
        # Insert actual source callback into a single-clock ROTOR/BEMF period.
        rows.insert(9,event(0,2_999_000,"SWITCH_FOCUS",24,1,15,10,50,3))
        for i,e in enumerate(rows):
            e["seq"]=i+1
        data=convert([line(x) for x in rows])
        self.assertIn("SWITCH_FOCUS",[e["kind"] for e in data["events"]])
        self.assertEqual(data["samples"][-1]["pwm_six_pad_mask"],24)
        self.assertEqual(data["samples"][-1]["pwm_mask_source_kind"],"SWITCH_FOCUS")
        self.assertEqual(data["samples"][-1]["pwm_gate"],True)
        self.assertFalse(data["summary"]["motor_p1_stability_qualified"])
    def test_source_time_reverse_rejected(self):
        rows=fixture();rows[6]["vns"]=0
        with self.assertRaisesRegex(SourceTraceError,"Gap/time reversal"):
            convert([line(x) for x in rows])
    def test_requires_exact_original_elf(self):
        with self.assertRaisesRegex(SourceTraceError,"Pinned Original"):
            NativeSourceReducer("a"*64)
        with self.assertRaisesRegex(SourceTraceError,"Pinned Original"):
            convert([line(x) for x in fixture()],elf_sha256="a"*64)
    def test_bemf_requires_same_clock_rotor_event(self):
        rows=fixture();rows[3]["vns"]=1_000_001
        with self.assertRaisesRegex(SourceTraceError,"same-clock"):
            convert([line(x) for x in rows])
    def test_cannot_invent_source_from_non_event_lines(self):
        with self.assertRaisesRegex(SourceTraceError,"No real"):
            convert(["ESC_SIM_WWDT_EXPIRED\n","QEMU started\n"])
    def test_mask_not_stale_or_reconstructed_from_duty(self):
        rows=fixture()
        r=NativeSourceReducer()
        for x in rows:
            got=r.ingest(x)
        self.assertIsNone(got["sample"]["pwm_six_pad_mask"])
        self.assertIsNone(got["sample"]["pwm_gate"])
        self.assertNotIn("pwm_duties",got["sample"])
    def test_no_virtual_time_rescaling_or_host_clock(self):
        d=convert([line(x) for x in fixture()])
        self.assertEqual([x["t_ns"] for x in d["samples"]],
                         [1_000_000,3_000_000])
        self.assertEqual(d["metadata"]["timebase"],"QEMU_CLOCK_VIRTUAL")
    def test_wwdt_feed_must_come_from_real_source_event(self):
        rows=fixture()
        rows[-2:]=[event(9,2_100_000,"WWDT_FEED",12,48),
                   event(10,3_000_000,"ROTOR",-9876,200,-200,0,200,2000),
                   event(11,3_000_000,"BEMF_FRONTEND",1800,1810,1820,0,2060,0)]
        d=convert([line(x) for x in rows])
        self.assertEqual(d["samples"][-1]["wwdt_feed_count"],1)
        self.assertIn("WWDT_FEED",[x["kind"] for x in d["events"]])
    def test_event_count_budget_is_fail_closed(self):
        r=NativeSourceReducer()
        for i in range(1,MAX_PENDING_EVENTS+1):
            r.ingest(event(i,i,"DSHOT",i,1,448))
        with self.assertRaisesRegex(SourceTraceError,"packet budget"):
            r.ingest(event(MAX_PENDING_EVENTS+1,MAX_PENDING_EVENTS+1,
                           "DSHOT",0,0,448))

if __name__=="__main__":
    unittest.main(verbosity=2)
