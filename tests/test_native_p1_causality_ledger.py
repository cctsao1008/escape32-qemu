#!/usr/bin/env python3
"""Causality ledger tests: original event semantics, no diagnostic P1 waiver."""
import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.native_p1_causality_ledger import diagnose, run
from tools.native_p0_strict import parse_events


def ev(seq, ns, kind, *fields):
    return {"seq":seq,"vns":ns,"kind":kind,
            "data":tuple(fields or (0,0,0,0,0,0))}


def line(e):
    return ("qemu-system-arm: E62_P0_EVENT seq="+str(e["seq"]) +
            " vns="+str(e["vns"])+" kind="+e["kind"]+" "+
            " ".join(a+"="+str(v) for a,v in zip(
                "abcdef",e["data"]))+"\n")


class CausalLedgerTest(unittest.TestCase):
    def events(self):
        return [
            ev(1,0,"DSHOT",1500,1,448,0,0,0),
            ev(2,100_000,"SWITCH",9,1,15,0,0,0),
            ev(3,200_000,"PWM_PAIR",2,9,15,-524,1,0),
            ev(4,1_000_000,"ROTOR",60000,100,20000,-20000,0,800000),
            ev(5,2_000_000,"DSHOT",1501,1,448,0,0,0),
            ev(6,3_000_000,"ROTOR",-70000,-10,45000,-25000,-20000,-3508971),
            ev(7,4_000_000,"CMP_FILTER",1,1,2100,2048,0,0),
            ev(8,5_000_000,"CAP1",200,1,2,2,0,0),
            ev(9,5_100_000,"CAP1_ACK",2,1,2,200,0,0),
            ev(10,9_000_000,"TIMG12",1,1,100,0,0,0),
            ev(11,9_100_000,"TIMG12_ACK",1,1,100,0,0,0),
            ev(12,10_000_000,"PWM_PAIR",3,33,15,-120,10,0),
            ev(13,11_000_000,"ROTOR",90000,50,3000,-1000,-2000,300000),
            ev(14,12_000_000,"DSHOT",1502,1,448,0,0,0),
        ]

    def test_pre_feedback_reverse_high_current_and_sixpad_provenance(self):
        report=diagnose("direct20",self.events(),{
            "status":"FAIL_P1_SIM_ONLY_OBSERVABILITY",
            "qualified":False,"significant_rotor_direction_changes":2,
            "unwaived_observability_failures":[
                "STARTUP_SIGNIFICANT_DIRECTION_REVERSAL"]})
        self.assertEqual(report["diagnostic_recomputed_direction_changes"],2)
        self.assertTrue(
            report["first_negative_speed_before_first_post_anchor_timg12"])
        self.assertTrue(
            report["first_sign_change_before_first_post_anchor_timg12"])
        self.assertEqual(
            report["first_50ms_after_anchor"]["peak_abs_phase_current_a"],
            45.0)
        self.assertAlmostEqual(
            report["first_50ms_after_anchor"]["minimum_torque_nm"],-3.508971)
        self.assertTrue(
            report["pwm_pair_sector_sequence_start"][0][
                "source_pair_id_consistent"])
        self.assertEqual(
            report["pwm_pair_sector_sequence_start"][0][
                "raw_aq_db_gate_word"],15)
        self.assertFalse(report["acceptance_policy_modified"])
        self.assertFalse(report["p1_source_qualified"])

    def test_10pct_stage_kept_separate_from_later_20pct_command(self):
        samples=[
            ev(1,0,"DSHOT",1500,1,248,0,0,0),
            ev(2,500_000_000,"DSHOT",2000,2,448,0,0,0),
            ev(3,501_000_000,"ROTOR",55000,1,20000,-20000,0,-150000),
            ev(4,502_000_000,"ROTOR",-56000,0,22000,-22000,0,-300000),
            ev(5,503_000_000,"DSHOT",2001,2,448,0,0,0),
        ]
        report=diagnose("steps",samples)
        self.assertEqual(report["anchor_kind"],"FIRST_GE20PCT")
        self.assertEqual(report["relative_to_comparison_anchor_ms"][
            "first_negative_torque_below_minus0p1nm"],1.0)
        self.assertEqual(report["relative_to_comparison_anchor_ms"][
            "first_reverse_minus50rpm"],2.0)
        self.assertIsNone(report["p1_source_qualified"])

    def test_missing_trace_fails_closed_without_fabricating_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            out=folder/"report.json"
            self.assertEqual(run([("direct20",folder/"missing.log",
                                    folder/"missing.json")],out),1)
            saved=json.loads(out.read_text())
            self.assertEqual(saved["status"],"SOURCE_DIAGNOSTIC_INCOMPLETE")
            self.assertFalse(saved["qualified"])

    def test_counter_disagreement_is_reported_not_waived(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            events=folder/"source.log"
            verdict=folder/"p1.json"
            output=folder/"causal.json"
            events.write_text("".join(map(line,self.events())))
            verdict.write_text(json.dumps({
                "qualified":False,"status":"FAIL_P1_SIM_ONLY_OBSERVABILITY",
                "significant_rotor_direction_changes":337}))
            self.assertEqual(run([("direct20",events,verdict)],output),1)
            saved=json.loads(output.read_text())
            self.assertIn("DIRECTION_CHANGE_COUNTER_DISAGREEMENT",
                          saved["issues"][0])
            self.assertFalse(saved["qualified"])


if __name__=="__main__":
    unittest.main(verbosity=2)
