#!/usr/bin/env python3
"""QEMU source-only audio/divider and phase-mask diagnostic regressions."""
import unittest
from tools.native_p0_strict import parse_events,TraceError
from tools.e62_audio_motor_timeline import analyze,_pair_from_mask
SHA="05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"

def line(n,ns,kind,a=0,b=0,c=0,d=0,e=0,f=0):
    return (f"E62_P0_EVENT seq={n} vns={ns} kind={kind} "+
            f"a={a} b={b} c={c} d={d} e={e} f={f}\n")
def fixture():
    stages=[{"kind":"hold","duration_ms":2,"permille":v} for v in [0,200,0,200,0]]
    scenario={"schema":"e62.native.dshot.v1","protocol":"DSHOT600",
              "guest_ready_gating":False,"frame_period_ns":1000000,
              "stages":stages}
    evidence={"original_elf_sha256":SHA,"host_guest_register_writes":False,
              "used_guest_wfi_or_gdb":False,"experimental_candidate_not_original":False,
              "configured_dshot_frames":10,"autonomous_dshot":{"sent":10}}
    payload=[]
    # Source-owned 1kHz frames, first two timestamps at 0 and 1ms
    for i in range(10):payload.append((i*1000000+1,"DSHOT",(i,i//2,0,0,0,0)))
    payload.extend([
       (500,"PWM_TBCTL",(2,22,7000,6250000,1,0)),
       (800,"PWM_AUDIO_PERIOD",(7000,7700,22,6250000,1,0)),
       (1500000,"PWM_TBCTL",(22,6,1666,100000000,1,0)),
       (2100000,"PWM_PAIR",(8,24,15,0,0,0)),
       (2500000,"ROTOR",(120000,-524,0,0,0,0)),
       (6500000,"PWM_PAIR",(8,24,15,0,0,0)),
       (7000000,"ROTOR",(-155000,-520,0,0,0,0)),
    ])
    payload.sort(key=lambda x:x[0])
    return parse_events([line(n+1,t,k,*args) for n,(t,k,args) in enumerate(payload)]),evidence,scenario

class AudioMotorSourceTest(unittest.TestCase):
    def test_audio_ends_before_both_positive_demands_no_p1_claim(self):
        ev,meta,s=fixture()
        d=analyze(ev,meta,s)
        self.assertTrue(d["audio_candidate_before_first_demand"])
        self.assertTrue(d["clock_div2_write_after_last_audio_before_first_demand"])
        self.assertEqual(d["audio_candidate_in_positive_demands"],0)
        self.assertFalse(d["p1_qualified"])
        self.assertFalse(d["guest_audio_owner_directly_observed"])
        self.assertFalse(d["hardware_qualified"])
        self.assertEqual(d["stage_evidence"][1]["first_pairs"],[8])
    def test_late_music_hardware_candidate_reported_not_suppressed(self):
        ev,meta,s=fixture()
        t=2500001
        ev.append({"seq":ev[-1]["seq"]+1,"vns":9000001,
                   "kind":"PWM_AUDIO_PERIOD","data":(1,2,22,6250000,1,0)})
        # In-memory analysis permits late appended evidence; parser on disk
        # continues to enforce monotone timestamp and contiguous seq.
        ev[-1]["vns"]=3500001
        self.assertEqual(analyze(ev,meta,s)["audio_candidate_in_positive_demands"],1)
    def test_pair_decode_not_motor_direction_assumption(self):
        self.assertEqual(_pair_from_mask(24),8)
        self.assertEqual(_pair_from_mask(9),2)
        self.assertIsNone(_pair_from_mask(0))
        self.assertIsNone(_pair_from_mask(3))
    def test_bad_guest_or_source_is_rejected_not_waived(self):
        ev,meta,s=fixture()
        meta["host_guest_register_writes"]=True
        with self.assertRaises(ValueError):analyze(ev,meta,s)
        meta["host_guest_register_writes"]=False
        s["guest_ready_gating"]=True
        with self.assertRaises(ValueError):analyze(ev,meta,s)
        with self.assertRaises(TraceError):
            parse_events([line(1,100,"PWM_TBCTL"),
                          line(3,90,"PWM_TBCTL")])
if __name__=="__main__":
    unittest.main(verbosity=2)
