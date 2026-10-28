#!/usr/bin/env python3
"""No-WFI original source neutral-energy audit: source ledger and causal limits."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_source_energy_audit import (
    EnergyAuditError, audit, parse_source, WINDOW_NS
)

def fixture(*, corrupt=False):
    raw=[
        (999_000_000,"DSHOT",[1000,0,448,0,0,0]),
        (999_200_000,"ENERGY",[1000,100,200,300,100,300]),
        (999_300_000,"INVARIANT",[1000,100,0,0,0,0]),
        (1_000_000_000,"DSHOT",[1001,0,0,0,0,0]),
        (1_000_100_000,"ENERGY",[1050,100,210,340,100,300]),
        (1_000_200_000,"INVARIANT",[1001,100,0,0,0,0]),
        (1_001_000_000,"PWM_PAIR",[2,9,15,0,0,0]),
        (1_002_000_000,"PWM_PAIR",[3,33,15,0,0,0]),
        (1_003_000_000,"CAP1",[2,0,0,0,0,0]),
        (1_004_000_000,"TIMG12",[1,1,0,0,0,0]),
        (1_034_000_000,"ENERGY",[1000,110,310,180,100,300]),
        (1_034_100_000,"INVARIANT",[1002,110,0,0,0,0]),
        (1_036_000_000,"ENERGY",[1000,110,310,180,100,300]),
    ]
    if corrupt:
        raw[10]=(raw[10][0],raw[10][1],
                 [1000,110,300,180,100,300])
    return [{"seq":i+1,"vns":ns,"kind":kind,"data":data}
            for i,(ns,kind,data) in enumerate(raw)]

class Tests(unittest.TestCase):
    def test_energy_balance_return_and_real_power_pairs(self):
        result=audit(fixture())
        self.assertEqual(result["trigger"]["previous_dshot_raw"],448)
        self.assertEqual(result["trigger"]["t_ns"],1_000_000_000)
        self.assertEqual(result["window"]["first_energy_ns"],1_000_100_000)
        self.assertEqual(result["window"]["last_energy_ns"],1_034_000_000)
        self.assertEqual(result["energy_delta_j"]["bus"],-50e-9)
        self.assertAlmostEqual(result["energy_delta_j"]["bemf"],-160e-9)
        self.assertEqual(result["energy_delta_j"]["copper"],100e-9)
        self.assertEqual(result["energy_delta_j"]["diode"],10e-9)
        self.assertEqual(result["source_events_in_window"]["PWM_PAIR"],2)
        self.assertEqual(len(result["powered_pwm_pairs_after_neutral"]),2)
        self.assertEqual(result["late_full_switch_events"],0)
        self.assertFalse(result["hardware_qualified"])
        self.assertFalse(result["motor_p1_stability_qualified"])
        self.assertIn("CAUSAL_MECHANISM_OPEN",result["classification"])
    def test_roundtrip_raw_source_logger(self):
        lines=[]
        for x in fixture():
            a,b,c,d,e,f=x["data"]
            lines.append(f"E62_P0_EVENT seq={x['seq']} vns={x['vns']} "
                         f"kind={x['kind']} a={a} b={b} c={c} d={d} e={e} f={f}\n")
        self.assertEqual(audit(parse_source(lines))["source_event_count"],13)
    def test_missing_source_rejected(self):
        with self.assertRaisesRegex(EnergyAuditError,"Missing actual"):
            parse_source(["not a source event"])
    def test_gap_rejected(self):
        rows=fixture()
        rows[4]["seq"]=20
        with self.assertRaisesRegex(EnergyAuditError,"Source order"):
            audit(rows)
    def test_no_nonzero_to_zero_rejected(self):
        rows=fixture()
        rows[3]["data"][2]=448
        with self.assertRaisesRegex(EnergyAuditError,"No observed DShot"):
            audit(rows)
    def test_ledger_integrity_fail_closed(self):
        with self.assertRaisesRegex(EnergyAuditError,"ledger inconsistent"):
            audit(fixture(corrupt=True))
    def test_full_window_coverage_required(self):
        rows=fixture()[:-1]
        with self.assertRaisesRegex(EnergyAuditError,"does not cover"):
            audit(rows)
    def test_window_bound(self):
        with self.assertRaisesRegex(EnergyAuditError,"1..500"):
            audit(fixture(),window_ns=600_000_000)
    def test_invariant_limit(self):
        rows=fixture()
        rows[5]["data"][3]=10001
        with self.assertRaisesRegex(EnergyAuditError,"invariant exceeded"):
            audit(rows)
    def test_focus_events_correlate_without_becoming_strict_switch(self):
        rows=fixture()
        rows.append({"seq":0,"vns":1_001_500_000,
                     "kind":"SWITCH_FOCUS","data":[24,1,15,1200,500,1]})
        rows.sort(key=lambda x:x["vns"])
        for i,row in enumerate(rows):
            row["seq"]=i+1
        result=audit(rows)
        self.assertEqual(result["source_events_in_window"]["SWITCH_FOCUS"],1)
        self.assertEqual(result["late_full_switch_events"],0)
        self.assertEqual(result["focused_switching_source_events"][0]["six_pad_mask"],24)
        self.assertEqual(result["focused_switching_source_events"][0]["gate_word"],15)
        self.assertTrue(result["focused_switch_observation_complete"])
        self.assertFalse(result["motor_p1_stability_qualified"])
    def test_focused_switch_budget_overflow_fails_closed(self):
        rows=fixture()
        rows.append({"seq":0,"vns":1_001_500_000,
                     "kind":"SWITCH_FOCUS_LIMIT","data":[12000,12000,0,0,0,0]})
        rows.sort(key=lambda x:x["vns"])
        for i,row in enumerate(rows):
            row["seq"]=i+1
        with self.assertRaisesRegex(EnergyAuditError,"budget exceeded"):
            audit(rows)

if __name__=="__main__":
    unittest.main(verbosity=2)
