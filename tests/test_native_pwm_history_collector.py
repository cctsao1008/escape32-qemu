#!/usr/bin/env python3
"""Original Guest WFI read-only PWM history collector host regressions.

No fabricated native firmware PASS. QEMU ring fixtures do not represent
physical switching edges. Tests prove only cursor, continuity, overflow
and partial-trace semantics.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/"tests"))

from test_native_pwm_history import fixture
from tools.native_pwm_history_collector import NativeWfiPWMHistoryCollector
from tools.native_pwm_history import BASE,WORDS
from tools.sitl_trace import SitlTraceRecorder

FIRST=(0,4,0,0,0,0)
SIX=[
    FIRST,
    (100,5,0,21,0,0),
    (250,1,21,20,25,0),
    (400,1,20,16,40,0),
    (600,1,16,0,60,0),
    (1000,2,0,21,0,1),
]


def reader(records):
    return fixture(records).__getitem__


def attach(records=None):
    c=NativeWfiPWMHistoryCollector()
    val=c.attach(reader(records or [FIRST]),
                 checkpoint="native_gate_return_before_sustained_motor")
    assert val["first_in_scope_sequence"]==(len(records) if records else 1)
    return c


class NativeWfiIncrementalHistoryTests(unittest.TestCase):
    def test_read_only_guest_wfi_incremental_six_edges_and_zero(self):
        c=attach()
        p1=c.poll(reader(SIX),wfi=1,ecap_elapsed_ns=5000)
        self.assertEqual(p1["new_events"],5)
        self.assertEqual(p1["missing_since_previous_poll"],0)
        self.assertEqual([x["sequence"] for x in c.events],list(range(1,6)))
        self.assertEqual(c.events[1]["virtual_ns"],250)
        self.assertEqual(c.events[-1]["kind"],
                         "QEMU_ORIGINAL_PWM_ZERO_CALLBACK")
        self.assertTrue(c.document()["complete_since_gate_return"])
        p2=c.poll(reader(SIX),wfi=2,ecap_elapsed_ns=10000)
        self.assertEqual(p2["new_events"],0)
        self.assertEqual(len(c.events),5)
        next_records=SIX+[
            (1250,1,21,20,25,1),
            (2000,2,20,21,0,2),
        ]
        p3=c.poll(reader(next_records),wfi=3,ecap_elapsed_ns=15000)
        self.assertEqual(p3["new_events"],2)
        self.assertEqual(c.events[-1]["sequence"],7)
        self.assertEqual(c.events[-1]["observed_at_native_wfi"],3)
        self.assertTrue(c.document()["complete_since_gate_return"])
        self.assertFalse(c.document()["complete_since_qemu_pwm_reset"])
        self.assertFalse(c.document()["physical_mosfet_edges_qualified"])
        self.assertFalse(c.document()["current_continuous_motor_plant_input_qualified"])

    def test_pre_attach_overflow_is_not_automatically_an_in_scope_gap(self):
        initial=[(i*10,7,0,0,0,0) for i in range(140)]
        c=attach(initial)
        self.assertEqual(c.attach_dropped,12)
        self.assertEqual(c.attach_total,140)
        later=initial+[(1400,7,0,0,0,0)]
        self.assertEqual(c.poll(reader(later),wfi=1,
                                ecap_elapsed_ns=5000)["new_events"],1)
        self.assertEqual(c.in_scope_missing_events,0)
        self.assertTrue(c.document()["complete_since_gate_return"])
        self.assertTrue(c.document()["attach"]["pre_attach_history_not_collected"])

    def test_unread_ring_overwrite_preserves_explicit_sequence_gap(self):
        c=attach()
        full=[FIRST]+[(i*10,7,0,0,0,0) for i in range(1,151)]
        p=c.poll(reader(full),wfi=1,ecap_elapsed_ns=5000)
        self.assertEqual(p["missing_since_previous_poll"],22)
        self.assertEqual(p["new_events"],128)
        self.assertEqual(c.in_scope_missing_events,22)
        self.assertEqual(c.events[0]["sequence"],23)
        self.assertFalse(c.document()["complete_since_gate_return"])
        self.assertEqual(c.document()["gaps"][0]["missing_events"],22)
        # Even after the next good poll, earlier lost evidence is NEVER healed.
        full.append((1510,7,0,0,0,0))
        c.poll(reader(full),wfi=2,ecap_elapsed_ns=10000)
        self.assertFalse(c.document()["complete_since_gate_return"])

    def test_ring_reset_after_gate_fails_closed_without_forged_wfi(self):
        c=attach(SIX)
        self.assertIsNone(c.poll(reader([FIRST]),wfi=1,
                                 ecap_elapsed_ns=5000))
        self.assertTrue(c.halted)
        self.assertEqual(len(c.polls),0)
        self.assertIn("reset",c.errors[0]["message"])
        self.assertFalse(c.document()["complete_since_gate_return"])

    def test_bad_event_order_prevents_partial_commit(self):
        c=attach()
        corrupted=[
            FIRST,(100,5,0,21,0,0),
            (250,1,21,20,25,0),
            (200,1,20,16,40,0),
        ]
        self.assertIsNone(c.poll(reader(corrupted),wfi=1,
                                 ecap_elapsed_ns=5000))
        self.assertEqual(len(c.events),0)
        self.assertTrue(c.halted)
        self.assertIn("discontinuity",c.errors[0]["message"])

    def test_midread_header_mutation_retains_prior_completed_evidence(self):
        c=attach()
        c.poll(reader(SIX),wfi=1,ecap_elapsed_ns=5000)
        value=fixture(SIX+[(1250,1,21,20,25,1)])
        seen=0
        def changing(addr):
            nonlocal seen
            if addr==BASE+0x28:
                seen+=1
                if seen==2:
                    return value[addr]+1
            return value[addr]
        c.poll(changing,wfi=2,ecap_elapsed_ns=10000)
        self.assertTrue(c.halted)
        self.assertEqual(len(c.events),5)
        self.assertEqual(c.last_wfi,1)
        self.assertEqual(c.errors[-1]["at_wfi"],2)
        self.assertFalse(c.document()["complete_since_gate_return"])

    def test_invalid_model_snapshot_remains_unqualified(self):
        c=attach()
        invalid=fixture(SIX)
        invalid[BASE+0x40]=1
        invalid[BASE+4] &= ~2
        c.poll(invalid.__getitem__,wfi=1,ecap_elapsed_ns=5000)
        self.assertEqual(c.invalid_since_attach,1)
        self.assertFalse(c.document()["complete_since_gate_return"])
        self.assertEqual(c.polls[0]["qemu_model_invalid_added"],1)

    def test_wfi_sequence_and_ecap_regression_fail_closed(self):
        for kwargs in (
            dict(wfi=2,ecap_elapsed_ns=5000),
            dict(wfi=1,ecap_elapsed_ns=-1),
        ):
            c=attach()
            c.poll(reader(SIX),**kwargs)
            self.assertTrue(c.halted)
            self.assertEqual(c.events,[])
        c=attach()
        c.poll(reader(SIX),wfi=1,ecap_elapsed_ns=5000)
        c.poll(reader(SIX),wfi=2,ecap_elapsed_ns=4000)
        self.assertEqual(len(c.events),5)
        self.assertTrue(c.halted)

    def test_bounded_storage_refuses_silent_drop(self):
        c=NativeWfiPWMHistoryCollector(max_recorded_events=2)
        c.attach(reader([FIRST]),
                 checkpoint="native_gate_return_before_sustained_motor")
        self.assertIsNone(c.poll(reader(SIX),wfi=1,
                                 ecap_elapsed_ns=5000))
        self.assertEqual(c.events,[])
        self.assertTrue(c.halted)
        self.assertIn("bounded",c.errors[0]["message"])

    def test_trace_persists_partial_on_original_motor_exception(self):
        c=attach()
        c.poll(reader(SIX),wfi=1,ecap_elapsed_ns=5000)
        bad=fixture(SIX)
        bad[BASE]=0
        c.poll(bad.__getitem__,wfi=2,ecap_elapsed_ns=10000)
        rec=SitlTraceRecorder(
            elf_sha256="a"*64,initial_electrical_degrees=-30,
            required_sectors=12,required_integrated_ns=90000000)
        rec.set_gate_origin(NS(index=0,elapsed_ns=0,
                        native_ecap_ticks=5000))
        rec.attach_pwm_history(c)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"partial.json"
            rec.write(path,error_type="ValueError")
            d=json.loads(path.read_text())
        self.assertEqual(d["capture_state"],"PARTIAL_EXCEPTION")
        self.assertEqual(d["pwm_history"]["stored_events"],5)
        self.assertEqual(len(d["pwm_history"]["collection_errors"]),1)
        self.assertFalse(d["pwm_history"]["complete_since_gate_return"])
        self.assertFalse(d["metadata"]["host_guest_register_writes"])
        self.assertFalse(d["pwm_history"]["motor_stability_qualified"])
        self.assertEqual(d["samples"],[])

    def test_guest_write_interface_absent_in_collector(self):
        c=attach()
        class ReadOnlyTransport:
            def __init__(self,registers):
                self.registers=registers
                self.reads=0
            def read(self, addr):
                self.reads+=1
                return self.registers[addr]
            def write(self,*_):
                raise AssertionError("Unexpected Guest/QTest write")
        transport=ReadOnlyTransport(fixture(SIX))
        c.poll(transport.read,wfi=1,ecap_elapsed_ns=5000)
        self.assertGreater(transport.reads,0)
        self.assertFalse(c.halted)

    def test_unqualified_or_failed_gate_attach_kept_without_motor_claim(self):
        c=NativeWfiPWMHistoryCollector()
        bad=fixture([FIRST])
        bad[BASE]=0
        self.assertIsNone(c.attach_safe(
            bad.__getitem__,
            checkpoint="native_gate_return_before_sustained_motor"))
        self.assertTrue(c.halted)
        self.assertFalse(c.attached)
        self.assertTrue(c.errors)
        self.assertFalse(c.document()["complete_since_gate_return"])


if __name__=="__main__":
    unittest.main(verbosity=2)
