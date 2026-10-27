#!/usr/bin/env python3
"""Read-only physical-power-to-CAP1/TIMG12 diagnostic contract."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_p1_first_feedback_latency import audit

def ev(seq,t,kind,*d):
    return {"seq":seq,"vns":t,"kind":kind,
            "data":tuple(d or [0,0,0,0,0,0])}

def demo(delay_ns=11_000_000):
    # CAP1 occurs before negative torque but timer fires after reversal.
    return [
        ev(1,1_000_000,"DSHOT",1510,0,448,0,0,0),
        ev(2,2_000_000,"PWM_PAIR",8,24,15,-524,301,0),
        ev(3,2_100_000,"SWITCH",24,1,15,0,0,0),
        ev(4,4_000_000,"CMP_FILTER",2,1,2200,2048,0,0),
        ev(5,4_000_000,"CAP1",200,2,2,2,0,0),
        ev(6,4_001_000,"CAP1_ACK",2,2,200,2,0,0),
        ev(7,7_000_000,"ROTOR",330000,1700,0,-27888,27888,-493476),
        ev(8,9_000_000,"ROTOR",-75000,2440,0,-34589,34589,-2973882),
        ev(9,4_000_000+delay_ns,"TIMG12",1,1,300,0,0,0),
        ev(10,4_000_500+delay_ns,"TIMG12_ACK",1,1,300,0,0,0),
        ev(11,4_010_000+delay_ns,"PWM_PAIR",4,6,15,0,310,0),
    ]

class FirstFeedbackTest(unittest.TestCase):
    def verdict(self):
        return {"status":"FAIL_P1_SIM_ONLY_OBSERVABILITY",
                "qualified":False,"significant_rotor_direction_changes":337}
    def test_cap_precedes_reverse_but_timg12_follows(self):
        r=audit(demo(),"", "direct20") if False else audit(
            demo(),self.verdict(),"direct20")
        self.assertEqual(r["first_capture_to_first_following_timg12_ms"],11)
        self.assertEqual(r["last_cap1_to_first_timg12_ms"],11)
        self.assertTrue(r["first_cap1_early_rejection_policy_consistent_not_proven"] is False)
        self.assertEqual(r["pinned_rel17_initial_ival_us"],10000)
        self.assertEqual(r["pinned_rel17_half_interval_ignore_before_us"],5000)
        self.assertEqual(r["cap1_events_before_first_following_timg12"],1)
        self.assertTrue(r["negative_torque_before_first_timg12"])
        self.assertTrue(r["reverse_before_first_timg12"])
        self.assertTrue(r["cap1_to_timg12_pairing_not_proven"])
        self.assertEqual(r["first_powered_pair_positive_torque_zero_theta_deg"],90)
        self.assertEqual(r["first_powered_pwm_pair"]["six_pad_mask"],24)
        self.assertEqual(r["preceding_source_command_at_first_power"]["data"][2],448)
        self.assertFalse(r["p1_source_qualified"])
    def test_multiple_capture_events_not_inferred_as_one_to_one(self):
        records=demo()
        records.insert(6,ev(7,5_000_000,"CAP1",201,2,2,2,0,0))
        records.sort(key=lambda x:x["vns"])
        for idx,rec in enumerate(records,1):
            rec["seq"]=idx
        r=audit(records,self.verdict(),"direct20")
        self.assertEqual(r["cap1_events_before_first_following_timg12"],2)
        self.assertTrue(r["first_cap1_early_rejection_policy_consistent_not_proven"])
        self.assertEqual(r["last_cap1_to_first_timg12_ms"],10.0)
        self.assertTrue(r["cap1_to_timg12_pairing_not_proven"])
    def test_initial_dshot_does_not_fake_early_motor_on_steps(self):
        records=demo()
        for e in records:
            if e["kind"]!="DSHOT":
                e["vns"]+=500_000_000
        records[0]["data"]=(1500,0,248,0,0,0)
        records.insert(1,ev(0,500_000_000,"DSHOT",2000,1,448,0,0,0))
        records.sort(key=lambda e:e["vns"])
        for i,x in enumerate(records,1):
            x["seq"]=i
        r=audit(records,self.verdict(),"steps")
        self.assertEqual(r["first_powered_pwm_after_positive_dshot"]["relative_ms"],501)
        self.assertEqual(r["preceding_source_command_at_first_power"]["data"][2],448)
        self.assertEqual(r["first_capture_to_first_following_timg12_ms"],11)
    def test_missing_physical_event_fails_closed(self):
        rec=[ev(1,0,"DSHOT",1,0,448,0,0,0)]
        with self.assertRaisesRegex(ValueError,"No physical original Guest PWM_PAIR"):
            audit(rec,self.verdict(),"direct20")
    def test_source_verdict_is_required(self):
        with self.assertRaisesRegex(ValueError,"Missing strict original"):
            audit(demo(),{"status":"PASS","qualified":True},"smoke")

if __name__=="__main__":
    unittest.main(verbosity=2)
