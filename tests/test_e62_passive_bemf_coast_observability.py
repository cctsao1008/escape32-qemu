"""SIM_ONLY BEMF source observability: negative controls are mandatory."""
import unittest

from tools.e62_passive_bemf_coast_observability import evaluate
from test_e62_restart_phase_torque_audit import scenario, events as rotor_events


def frontend_events(coast=300,phase_diff=1):
    s=scenario(coast)
    rows=rotor_events(s)
    restart=rows[3000+coast]["vns"]
    coast_start=restart-coast*1_000_000
    for i in range(300):
        t=coast_start+i*1_000_000+500_000
        contrast=(20 if i<100 else 5 if i<150 else
                  2 if i<200 else phase_diff)
        rows.append({"kind":"BEMF_FRONTEND","vns":t,
                    "data":(2047,2047+contrast,2047,2,2048,0)})
    if coast>300:
        for i in range(100):
            t=restart-(100-i)*1_000_000+500_000
            rows.append({"kind":"BEMF_FRONTEND","vns":t,
                        "data":(2047,2047+phase_diff,2047,2,2048,0)})
    return sorted(rows,key=lambda v:v["vns"]),s


class PassiveBEMFCoastAuditTest(unittest.TestCase):
    def test_one_code_is_not_phase_qualified(self):
        ev,s=frontend_events()
        r=evaluate(ev,s)
        self.assertEqual(r["classification"],
                         "INSUFFICIENT_MODEL_BEMF_CODE_CONTRAST")
        self.assertEqual(r["max_instantaneous_phase_to_phase_code_contrast"],1)
        self.assertFalse(r["passive_model_signal_qualified_for_rotor_angle"])
        self.assertFalse(r["firmware_enable_granted"])
        self.assertEqual(r["source_bemf_samples"],100)
        self.assertEqual([x["max_phase_code_contrast"]
                          for x in r["first_300ms_passive_coast_decay_50ms_buckets"]],
                         [20,20,5,2,1,1])

    def test_five_codes_still_cannot_grant_angle(self):
        ev,s=frontend_events(3000,phase_diff=5)
        r=evaluate(ev,s)
        self.assertEqual(r["classification"],
                         "SOME_MODEL_CODE_CONTRAST_DIRECTION_STILL_UNQUALIFIED")
        self.assertFalse(r["passive_model_signal_qualified_for_rotor_angle"])
        self.assertFalse(r["firmware_enable_granted"])
        self.assertEqual(len(r["first_300ms_passive_coast_decay_50ms_buckets"]),6)

    def test_missing_phase_source_is_rejected(self):
        ev,s=frontend_events()
        ev=[e for e in ev if e["kind"]!="BEMF_FRONTEND"]
        with self.assertRaisesRegex(ValueError,"Missing/duplicated"):
            evaluate(ev,s)

    def test_late_active_coast_guest_capture_is_rejected(self):
        ev,s=frontend_events()
        start=next(e for e in ev if e["kind"]=="DSHOT"
                   and e["data"][0]==3000)["vns"]
        ev.append({"kind":"CAP1_ACK","vns":start+250_000_000,
                   "data":(0,0,0,0,0,0)})
        with self.assertRaisesRegex(ValueError,"Coast still carries"):
            evaluate(sorted(ev,key=lambda e:e["vns"]),s)

    def test_invalid_ADC_code_is_rejected(self):
        ev,s=frontend_events()
        idx=next(i for i,e in enumerate(ev)
                 if e["kind"]=="BEMF_FRONTEND")
        ev[idx]["data"]=(4096,2048,2048,2,2048,0)
        with self.assertRaisesRegex(ValueError,"Invalid three phase"):
            evaluate(ev,s)

    def test_disconnected_source_clock_is_rejected(self):
        ev,s=frontend_events()
        e=next(e for e in ev if e["kind"]=="DSHOT" and
               e["data"][0]==3200)
        e["vns"]+=150
        with self.assertRaisesRegex(ValueError,"1kHz clock drift"):
            evaluate(sorted(ev,key=lambda e:e["vns"]),s)

    def test_invalid_stage_input_is_rejected(self):
        ev,s=frontend_events()
        s["stages"][2]["permille"]=200
        with self.assertRaisesRegex(ValueError,"neutral/coast/restart"):
            evaluate(ev,s)

if __name__=="__main__":
    unittest.main()
