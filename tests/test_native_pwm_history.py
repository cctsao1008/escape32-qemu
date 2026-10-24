#!/usr/bin/env python3
"""G13B3 Historical QEMU PWM event ABI negative controls (host only)."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools.native_pwm_history import (
    BASE,MAGIC,ABI,CAPACITY,WORDS,read_native_pwm_history)


def fixture(records=None):
    # (virtual-ns, kind, before, after, counter, zero)
    if records is None:
        records=[
            (0,4,0,21,0,0),
            (250,1,21,20,25,0),
            (400,1,20,16,40,0),
            (600,1,16,0,60,0),
            (1000,2,0,21,0,1),
        ]
    total=len(records)
    count=min(total,CAPACITY)
    dropped=total-count
    last=records[-1][0] if records else 0
    regs={
        BASE:MAGIC, BASE+4:0x0b|(4 if dropped else 0),
        BASE+8:ABI, BASE+0xc:CAPACITY,
        BASE+0x10:count,
        BASE+0x14:total & 0xffffffff,
        BASE+0x18:total >>32,
        BASE+0x1c:dropped & 0xffffffff,
        BASE+0x20:dropped >>32,
        BASE+0x24:records[-1][3] if records else 0,
        BASE+0x28:records[-1][5] if records else 0,
        BASE+0x2c:0,BASE+0x30:last & 0xffffffff,
        BASE+0x34:last >>32,
        BASE+0x38:100_000_000,
        BASE+0x3c:WORDS,BASE+0x40:0,
    }
    for j,(t,k,b,a,ctr,z) in enumerate(records[-CAPACITY:]):
        words=[t&0xffffffff,t>>32,k,b,a,ctr,z,0x10000]
        for i,w in enumerate(words):
            regs[BASE+0x80+(j*WORDS+i)*4]=w
    return regs


class NativeHistoricalPWMModel(unittest.TestCase):
    def test_real_clocked_event_types_and_monotonic_provenance(self):
        regs=fixture()
        h=read_native_pwm_history(regs.__getitem__)
        self.assertEqual(len(h.observed_events),5)
        self.assertEqual(h.observed_events[1].virtual_ns,250)
        self.assertEqual(h.observed_events[1].kind,
                         "QEMU_CLOCKED_AQ_DB_EDGE")
        self.assertEqual(h.observed_events[-1].kind,
                         "QEMU_ORIGINAL_PWM_ZERO_CALLBACK")
        self.assertEqual(h.observed_events[-1].native_zero_count,1)
        d=h.to_dict()
        self.assertTrue(d["chronological_qemu_callbacks_recorded"])
        self.assertTrue(d["complete_history_qualified"])
        for k in (
            "historical_physical_mosfet_edges_qualified",
            "gate_driver_deadtime_measured",
            "real_power_stage_freewheel_measured",
            "external_pin_waveform_measured",
            "current_continuous_plant_input_qualified",
            "strict_native_rotor_gate_qualified_by_this_trace",
        ):
            self.assertFalse(d[k])

    def test_ring_wrap_is_explicit_and_not_a_full_history(self):
        records=[(j*10,7,0,0,0,0) for j in range(138)]
        regs=fixture(records)
        h=read_native_pwm_history(regs.__getitem__)
        self.assertEqual(h.dropped_events,10)
        self.assertEqual(h.total_events_since_pmw_reset,138)
        self.assertEqual(h.observed_events[0].sequence,10)
        self.assertEqual(h.observed_events[-1].sequence,137)
        self.assertFalse(h.to_dict()["complete_history_qualified"])

    def test_empty_uninitialized_or_invalid_model_never_qualified(self):
        empty=fixture([])
        model=read_native_pwm_history(empty.__getitem__)
        self.assertFalse(model.to_dict()["complete_history_qualified"])
        invalid=fixture()
        invalid[BASE+4] &= ~2
        model=read_native_pwm_history(invalid.__getitem__)
        self.assertFalse(model.to_dict()["complete_history_qualified"])

    def test_invalid_model_count_forces_not_complete(self):
        regs=fixture()
        regs[BASE+0x40]=1
        h=read_native_pwm_history(regs.__getitem__)
        self.assertFalse(h.to_dict()["complete_history_qualified"])

    def test_never_claims_unobserved_guest_edge_at_plan_only(self):
        regs=fixture([(0,4,0,0,0,0)])
        h=read_native_pwm_history(regs.__getitem__)
        self.assertFalse(any(x.kind=="QEMU_CLOCKED_AQ_DB_EDGE"
                             for x in h.observed_events))
        self.assertFalse(h.to_dict()["current_continuous_plant_input_qualified"])

    def test_misordered_timestamp_rejected(self):
        regs=fixture()
        regs[BASE+0x80+2*WORDS*4]=100
        with self.assertRaisesRegex(ValueError,"ordering"):
            read_native_pwm_history(regs.__getitem__)

    def test_causal_mask_discontinuity_rejected(self):
        regs=fixture()
        regs[BASE+0x80+(2*WORDS+3)*4]=17
        with self.assertRaisesRegex(ValueError,"continuity"):
            read_native_pwm_history(regs.__getitem__)

    def test_zero_callback_nonzero_counter_rejected(self):
        regs=fixture()
        regs[BASE+0x80+(4*WORDS+5)*4]=17
        with self.assertRaisesRegex(ValueError,"counter zero"):
            read_native_pwm_history(regs.__getitem__)

    def test_fabricated_noop_edge_refused(self):
        regs=fixture()
        regs[BASE+0x80+(1*WORDS+4)*4]=21
        with self.assertRaisesRegex(ValueError,"did not change"):
            read_native_pwm_history(regs.__getitem__)

    def test_malformed_or_missing_mmio_mapping_refused(self):
        for addr,val in ((BASE,0),(BASE+8,2),(BASE+0xc,8),
                         (BASE+0x3c,6),(BASE+4,0x80)):
            regs=fixture()
            regs[addr]=val
            with self.assertRaises(ValueError):
                read_native_pwm_history(regs.__getitem__)

    def test_header_mutation_mid_read_rejected(self):
        regs=fixture()
        count=0
        def changing(address):
            nonlocal count
            if address==BASE+0x28:
                count+=1
                if count>1:
                    return regs[address]+1
            return regs[address]
        with self.assertRaisesRegex(ValueError,"ring changed"):
            read_native_pwm_history(changing)

    def test_truncated_header_rejected_when_dropped_count_falsified(self):
        regs=fixture([(j,7,0,0,0,0) for j in range(CAPACITY+1)])
        regs[BASE+0x1c]=0
        with self.assertRaisesRegex(ValueError,"event counts"):
            read_native_pwm_history(regs.__getitem__)

    def test_one_genuine_gate_marker_not_silicon_gate_measurement(self):
        regs=fixture([(125,7,0,0,12,0)])
        regs[BASE+0x80+7*4]=0x1000f
        h=read_native_pwm_history(regs.__getitem__)
        e=h.observed_events[0]
        self.assertEqual(e.kind,"QEMU_RAW_PB13_GPIO_PINCM_BOUNDARY")
        self.assertEqual(e.raw_pb13,1)
        self.assertTrue(e.pb13_doe)
        self.assertTrue(e.pb13_pinmux_valid)
        self.assertFalse(h.to_dict()["gate_driver_deadtime_measured"])


if __name__=="__main__":
    unittest.main(verbosity=2)
