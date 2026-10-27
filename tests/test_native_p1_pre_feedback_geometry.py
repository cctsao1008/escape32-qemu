#!/usr/bin/env python3
"""P1 early startup geometry is read-only and cannot override P1 FAIL."""
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_p1_pre_feedback_geometry import (
    KT,OFFSETS,torque_from_trace,pair_geometry,source_signature,
    analyze_records,
)


def event(seq,ns,kind,*values):
    return {"seq":seq,"vns":ns,"kind":kind,
            "data":tuple(values or [0]*6)}

def motor(seq,ns,rpm,iabc,theta=0):
    torque=KT*sum(i*math.sin(theta+o) for i,o in zip(iabc,OFFSETS))
    return event(seq,ns,"ROTOR",round(rpm*1000),round(theta*1000),
                 *(round(i*1000) for i in iabc),round(torque*1e6))

def line(e):
    return (f"E62_P0_EVENT seq={e['seq']} vns={e['vns']} "+
            f"kind={e['kind']} "+" ".join(
                f"{k}={v}" for k,v in zip("abcdef",e["data"]))+"\n")

class P1PreFeedbackGeometryTest(unittest.TestCase):
    def fixture(self):
        return [
            event(1,0,"DSHOT",1500,1,448,0,0,0),
            event(2,100000,"SWITCH",9,1,15,0,0,0),
            event(3,200000,"PWM_PAIR",2,9,15,0,1,0),
            motor(4,1000000,60,(0,-10,10)),
            motor(5,2000000,-70,(0,10,-10)),
            motor(6,3000000,-75,(0,15,-15)),
            event(7,4000000,"CAP1",200,1,2,2,0,0),
            event(8,4500000,"TIMG12",1,1,100,0,0,0),
        ]

    def test_negative_torque_with_positive_guest_pair_geometry(self):
        result=source_signature(self.fixture())
        pre=result["pre_first_timg12"]
        self.assertTrue(pre["first_pair"][
            "ideal_source_to_sink_current_would_generate_forward_torque"])
        self.assertTrue(result["negative_torque_before_first_timg12"])
        self.assertTrue(result["negative_speed_before_first_timg12"])
        self.assertEqual(result["first_negative_torque_relative_ms"],2.0)
        self.assertEqual(result["first_reverse_50rpm_relative_ms"],2.0)
        self.assertEqual(result["first_feedback_relative_ms"]["TIMG12"],4.5)
        self.assertEqual(result["source_torque_reconstruction"]["mismatch_count"],0)
        self.assertEqual(result["first_50ms_power_pair_invalid_count"],0)
        self.assertFalse(result["qualification"])

    def test_positive_pair_does_not_imply_positive_actual_current(self):
        p=pair_geometry(event(3,200000,"PWM_PAIR",2,9,15,0,1,0))
        self.assertEqual((p["hi_phase"],p["lo_phase"]),(0,1))
        self.assertTrue(p["source_pair_code_consistent"])
        self.assertTrue(p["positive_source_to_sink_current_torque_basis"]>0)
        self.assertTrue(p["not_a_measured_current_direction"])

    def test_detect_incorrect_source_torque_without_motor_tuning(self):
        bad=self.fixture()
        bad[4]=event(5,2000000,"ROTOR",-70000,0,0,10000,-10000,
                     1_000_000)  # Unphysical positive torque vs currents.
        result=source_signature(bad)
        self.assertGreater(result["source_torque_reconstruction"]["mismatch_count"],0)

    def test_missing_or_bad_source_is_not_pass(self):
        with tempfile.TemporaryDirectory() as root:
            result=analyze_records([("direct20",Path(root)/"missing",
                                     Path(root)/"missing-verdict")])
            self.assertFalse(result["qualified"])
            self.assertEqual(result["status"],
                             "FAIL_CLOSED_SOURCE_GEOMETRY_INCOMPLETE")
            self.assertTrue(result["issues"])

    def test_malformed_power_pair_visible_not_normalized(self):
        events=self.fixture()
        events[2]=event(3,200000,"PWM_PAIR",2,3,15,0,1,0)
        # Same-leg hi+lo cannot be silently mapped to a sector.
        result=source_signature(events)
        self.assertEqual(result["first_50ms_power_pair_invalid_count"],1)

if __name__=="__main__":
    unittest.main(verbosity=2)
