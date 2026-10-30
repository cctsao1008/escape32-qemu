"""Fail-closed #7 OC sensor-overrange safety oracle + exact hashed source."""
import tempfile
import unittest
import json
from pathlib import Path
from tools.native_p1_oc_fault_plan import load_oc_plan
from tools.native_p1_running_oc_audit import audit

STAGES=[(1500,0,0,1),(1000,0,200,5),(300,200,200,1),(200,0,0,1)]
SHA="05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0"
def fixture(phase="oc-u",start=2100,stop=2300):
    d={"schema":"e62.native.external-oc-sense.v1",
       "source":"adc_like_current_sense_overrange",
       "phase":phase,"assert_frame":start,"release_frame":stop,
       "expectation":"OST3_LATCHED_GATE_SAFE_OFF_NO_REARM"}
    with tempfile.TemporaryDirectory() as tmp:
        f=Path(tmp)/"oc.json"
        f.write_text(json.dumps(d))
        return load_oc_plan(f,STAGES)

def good_trace(plan):
    # This is a UNIT fixture, not substituted for real QEMU CI evidence.
    ev=[{"kind":"DSHOT","vns":999+i*1_000_000,
         "data":(i,0,0,0,0,0)} for i in range(3000)]
    ev.append({"kind":"PWM_PAIR","vns":1_900_000_999,
               "data":(0,0,0,0,0,0)})
    ev.sort(key=lambda e:e["vns"])
    log=("\nE62_NATIVE_EXTERNAL_OC_EDGE "
         f"vns={999+plan['assert_frame']*1000000} frame={plan['assert_frame']} "
         f"channel={plan['channel']} asserted=1 code=4095 trip=0x40000 irq=0x4\n"
         "E62_NATIVE_EXTERNAL_OC_EDGE "
         f"vns={999+plan['release_frame']*1000000} frame={plan['release_frame']} "
         f"channel={plan['channel']} asserted=0 code=1000 trip=0x40000 irq=0x4\n")
    evidence={"configured_dshot_frames":3000,"native_external_oc_sense_fault_plan":plan,
              "original_elf_sha256":SHA,"host_guest_register_writes":False,
              "used_guest_wfi_or_gdb":False,"synthetic_timed_bemf_enabled":False,
              "autonomous_dshot":{"sent":3000},
              "original_guest_after":{"valid_frame_feeds":2600},
              "receiver_after":{"native_ost_latched":0x40000,
                                "native_pwm_trip_latch":0x40000},
              "native_motor":{"actual_pwm_six_bit_mask":0},
              "pwm_source_after":{"running":False}}
    return ev,evidence,log

class NativeRunningOCSenseNegative(unittest.TestCase):
    def test_three_bounded_independent_phase_calendars(self):
        for phase,channel in (("oc-w",0),("oc-v",1),("oc-u",2)):
            plan=fixture(phase)
            self.assertEqual(plan["channel"],channel)
            e,d,l=good_trace(plan)
            x=audit(e,d,plan,l)
            self.assertTrue(x["qualified"],x["failures"])
            self.assertFalse(x["native_physical_motor_overcurrent_qualified"])

    def test_missing_source_edge_fails(self):
        p=fixture();e,d,l=good_trace(p)
        x=audit(e,d,p,l.splitlines()[1])
        self.assertFalse(x["qualified"])

    def test_wrong_channel_does_not_claim_another_phase(self):
        p=fixture();e,d,l=good_trace(p)
        l=l.replace("channel=2","channel=1")
        self.assertIn("OC_SOURCE_NOT_QEMU_VIRTUAL_FRAME_ALIGNED",
                      audit(e,d,p,l)["failures"])

    def test_unlatched_trip_does_not_pass(self):
        p=fixture();e,d,l=good_trace(p)
        l=l.replace("trip=0x40000","trip=0x0")
        self.assertFalse(audit(e,d,p,l)["qualified"])

    def test_genuine_running_pwm_required(self):
        p=fixture();e,d,l=good_trace(p)
        e=[x for x in e if x["kind"]!="PWM_PAIR"]
        self.assertFalse(audit(e,d,p,l)["qualified"])

    def test_pwm_after_fault_reject(self):
        p=fixture();e,d,l=good_trace(p)
        e.append({"kind":"PWM_PAIR","vns":2_200_000_999,
                  "data":(0,0,0,0,0,0)})
        self.assertFalse(audit(e,d,p,l)["qualified"])

    def test_source_fault_hash_required(self):
        p=fixture();e,d,l=good_trace(p)
        d["native_external_oc_sense_fault_plan"]={"sha256":"bad"}
        self.assertFalse(audit(e,d,p,l)["qualified"])

    def test_gate_off_and_latch_required(self):
        p=fixture();e,d,l=good_trace(p)
        d["native_motor"]["actual_pwm_six_bit_mask"]=1
        d["receiver_after"]["native_ost_latched"]=0
        self.assertFalse(audit(e,d,p,l)["qualified"])

    def test_bad_source_while_neutral_rejected(self):
        with self.assertRaisesRegex(ValueError,"positive drive"):
            fixture("oc-u",start=500,stop=700)

    def test_invalid_phase_fails_closed(self):
        with self.assertRaises(ValueError):
            fixture("oc-x")

if __name__=="__main__":
    unittest.main()
