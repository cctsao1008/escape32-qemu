#!/usr/bin/env python3
"""Strict native P0 controls: never manufacture causal/rotor PASS."""
import json, sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_p0_strict import parse_events,audit,TraceError
from tools.native_p0_reference_replay import decode_six_pad
PIN="05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"


def line(n,t,kind,*data):
    data=(*data,)*(1) if data else (0,0,0,0,0,0)
    if len(data)!=6:
        raise ValueError("six model fields")
    return (f"E62_P0_EVENT seq={n} vns={t} kind={kind} "+
            " ".join(f"{k}={v}" for k,v in zip("abcdef",data))+"\n")


def evidence():
    return {"original_elf_sha256":PIN,"host_guest_register_writes":False,
      "used_guest_wfi_or_gdb":False,"synthetic_timed_bemf_enabled":False,
      "legacy_synthetic_bemf_callbacks":0,"configured_dshot_frames":3000,
      "autonomous_dshot":{"sent":3000},
      "original_guest_after":{"valid_frame_feeds":2380,"serviced":824},
      "native_motor":{"model_fault":0,"status_flags":3,
                      "ost3_latch_activations":0},
      "receiver_after":{"native_pwm_trip_latch":0}}


class P0SourceAuditTest(unittest.TestCase):
    def test_event_timestamps_and_sequence_fail_closed(self):
        valid=[line(1,100,"CMP_FILTER",0,1,2048,2050,0,0),
               line(2,101,"CAP1",5,0,2,2,0,0)]
        self.assertEqual(len(parse_events(valid)),2)
        for bad in (
            [valid[0],line(3,101,"CAP1",0,0,0,0,0,0)],
            [valid[0],line(2,99,"CAP1",0,0,0,0,0,0)],
            [line(2,100,"CAP1",0,0,0,0,0,0)],
            ["E62_P0_EVENT invalid\n"]):
            with self.assertRaises(TraceError):
                parse_events(bad)

    def test_no_activity_or_wfi_cannot_pass(self):
        events=parse_events([line(1,1,"CMP_FILTER",0,0,0,0,0,0)])
        r=audit(events,evidence())
        self.assertFalse(r["qualified"])
        self.assertIn("NO_12_SOURCE_ORDERED_CAUSAL_CHAINS",
                      r["unwaived_failure_reasons"])
        altered=evidence();altered["used_guest_wfi_or_gdb"]=True
        r=audit(events,altered)
        self.assertIn("NOT_AUTONOMOUS_OR_GUEST_WRITES",
                      r["unwaived_failure_reasons"])

    def test_source_ledger_wrong_sign_fails(self):
        events=parse_events([
            line(1,1,"ENERGY",100,0,0,0,0,1),
            line(2,1,"INVARIANT",100,0,0,0,0,0),
        ])
        r=audit(events,evidence())
        self.assertFalse(r["qualified"])
        self.assertIn("NATIVE_ELECTRICAL_ENERGY_IDENTITY_FAILED",
                      r["unwaived_failure_reasons"])

    def test_physical_switch_decoder_rejects_overlap(self):
        with self.assertRaisesRegex(ValueError,"Unsafe"):
            decode_six_pad(3,1)
        self.assertEqual(decode_six_pad(0b1001,1).legs,("H","L","Z"))
        self.assertEqual(decode_six_pad(0b1001,0).legs,("Z","Z","Z"))


if __name__=="__main__":
    unittest.main(verbosity=2)
