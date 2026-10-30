#!/usr/bin/env python3
"""Negative controls for independent source-clock second-demand research oracle."""
import unittest

from tools.e62_experimental_second_demand_oracle import evaluate_second_demand
from tools.native_p1_qualification import commands_for_scenario

STAGES=[
    (1500,0,0,1),(1500,200,200,1),(1500,0,0,1),
    (1500,200,200,1),(300,0,0,1)
]
START=1_000_000_000
ONE_MS=1_000_000


def synthetic_events(*,second_cap=True,second_timg=True,
                     coast_pwm=False,reverse_second=False,
                     tamper_dshot=False):
    events=[]
    for i,(stage,dshot) in enumerate(commands_for_scenario(STAGES)):
        events.append({"vns":START+i*ONE_MS,"kind":"DSHOT",
                       "data":(i,stage,dshot,0,0,0)})
    for stage,start_idx in ((1,1500),(3,4500)):
        origin=START+start_idx*ONE_MS
        for k in range(20):
            t=origin+(100+k)*ONE_MS
            events.append({"vns":t,"kind":"PWM_PAIR","data":(0,)*6})
            if stage!=3 or second_cap:
                events.append({"vns":t+10,"kind":"CAP1_ACK","data":(0,)*6})
            if stage!=3 or second_timg:
                events.append({"vns":t+20,"kind":"TIMG12_ACK","data":(0,)*6})
        events.append({"vns":origin+250*ONE_MS,"kind":"ROTOR",
                       "data":(-70000 if stage==3 and reverse_second
                               else 70000,0,0,0,0,0)})
    if coast_pwm:
        events.append({"vns":START+3500*ONE_MS,"kind":"PWM_PAIR",
                       "data":(0,)*6})
    if tamper_dshot:
        events[4500]["data"]=(4500,3,0,0,0,0)
    events.sort(key=lambda e:e["vns"])
    return events


class SecondDemandOracleTest(unittest.TestCase):
    def test_valid_source_two_independent_feedback_windows(self):
        r=evaluate_second_demand(synthetic_events(),STAGES)
        self.assertTrue(r["pass"],r["failures"])
        self.assertEqual([w["source_counts"]["CAP1_ACK"] for
                          w in r["demand_windows"]],[20,20])
        self.assertFalse(r["coast"]["verified_complete_standstill"])

    def test_second_capture_cannot_borrow_from_first_demand(self):
        r=evaluate_second_demand(synthetic_events(second_cap=False),STAGES)
        self.assertFalse(r["pass"])
        self.assertIn("SECOND_DEMAND_REACQUISITION_GUEST_CLOSED_LOOP_NOT_PROVEN",
                      r["failures"])

    def test_second_delayed_commutation_ack_is_independent(self):
        r=evaluate_second_demand(synthetic_events(second_timg=False),STAGES)
        self.assertFalse(r["pass"])
        self.assertIn("SECOND_DEMAND_REACQUISITION_GUEST_CLOSED_LOOP_NOT_PROVEN",
                      r["failures"])

    def test_neutral_coast_must_stop_active_pairs(self):
        r=evaluate_second_demand(synthetic_events(coast_pwm=True),STAGES)
        self.assertFalse(r["pass"])
        self.assertIn("SECOND_DEMAND_COAST_UNEXPECTED_ACTIVE_COMMUTATION",
                      r["failures"])

    def test_second_rotor_reverses(self):
        r=evaluate_second_demand(synthetic_events(reverse_second=True),STAGES)
        self.assertFalse(r["pass"])
        self.assertIn("SECOND_DEMAND_REACQUISITION_SIGNIFICANT_REVERSE_ROTATION",
                      r["failures"])

    def test_source_dshot_values_cannot_be_replaced_by_host(self):
        r=evaluate_second_demand(synthetic_events(tamper_dshot=True),STAGES)
        self.assertFalse(r["pass"])
        self.assertIn("SECOND_DEMAND_DSHOT_SOURCE_MISMATCH",r["failures"])

    def test_no_valid_independent_coast_stage(self):
        bad=STAGES.copy()
        bad[2]=(100,0,0,1)
        r=evaluate_second_demand(synthetic_events(),bad)
        self.assertFalse(r["pass"])
        self.assertIn("SECOND_DEMAND_FIXTURE_SCHEMA_UNEXPECTED",r["failures"])


if __name__=="__main__":
    unittest.main()
