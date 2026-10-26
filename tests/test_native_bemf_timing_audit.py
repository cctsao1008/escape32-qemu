#!/usr/bin/env python3
"""G17/G18 synthetic forensic test; does not qualify original Guest."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.native_bemf_timing_audit import audit, _threshold_crossings

class NativeBemfForensicTests(unittest.TestCase):
    def fixture(self):
        pp=21
        ke=.0030904761904761904
        rpm=100.
        samples=[]
        for idx,angle in enumerate((-.25,.15,.45,.75,1.05),1):
            values=[ke*pp*(rpm*2*math.pi/60)*math.sin(angle+d)
                    for d in (0,-2*math.pi/3,2*math.pi/3)]
            codes=[round(4095*(1.65+.02*v)/3.3) for v in values]
            samples.append({
                "wfi":idx,"t_ns":idx*100,
                "motor_rpm":rpm,"electrical_rad":angle,
                "bemf_phase_v":values,"analog_adc_codes":codes,
                "sampling_qualifier":"EXTERNAL_CLOCKED_CURRENT_CONTINUOUS_NO_AVERAGE"
            })
        return {
            "format":"e62.sitl.native-wfi.v1",
            "scope":"SIM_ONLY_UNCALIBRATED_OPEN_STAR_MODEL",
            "metadata":{"host_guest_register_writes":False,
                "elf_sha256":"a"*64,
                "motor_model":{"electromagnetic_reciprocal":True,
                    "physical_motor_calibrated":False,
                    "pole_pairs":pp,
                    "bemf_constant_v_per_electrical_rad_s":ke,
                    "profile":"ecx87-kv147"}},
            "samples":samples,
            "events":[
                {"kind":"CAP1_ACCEPTED","sector":1,"t_ns":205,
                 "guest_step_before":1,"guest_step_after":2},
                {"kind":"TIMG12_SERVICED","sector":1,"t_ns":235,
                 "guest_step_before":1,"guest_step_after":2}],
            "native_result":{"significant_direction_reversals":2}
        }
    def test_bemf_formula_codes_and_guest_cap1_timg12(self):
        result=audit(self.fixture())
        self.assertTrue(result["model_to_fixture_bemf_consistency_pass"])
        self.assertEqual(result["ordered_cap1_service_pairs"],1)
        self.assertEqual(result["original_native_cap1_timg12_pairs"],1)
        case=result["sector_timing"][0]
        self.assertEqual(case["expected_comparator_phase"],0)
        self.assertEqual(case["expected_comparator_edge"],"rising")
        self.assertTrue(case["capture_has_matching_wfi_crossing_bracket"])
        self.assertEqual(case["cap1_after_crossing_bracket_end_ns"],5)
        self.assertFalse(case["cap1_after_crossing_bracket_end_is_exact_filter_delay"])
        self.assertEqual(case["cap1_to_service_us"],.03)
        self.assertEqual(result["simulated_rotor_direction_reversals"],2)
        self.assertIn("NOT_WAIVED",result["original_guest_strict_rotor_gate"])
    def test_bemf_wrong_code_and_value_rejected(self):
        x=self.fixture()
        x["samples"][1]["analog_adc_codes"][0]+=1
        self.assertFalse(audit(x)["model_to_fixture_bemf_consistency_pass"])
        x=self.fixture()
        x["samples"][1]["bemf_phase_v"][0]+=1.
        with self.assertRaisesRegex(ValueError,"disagrees"):
            audit(x)
    def test_cap1_after_service_is_not_a_pass(self):
        x=self.fixture()
        x["events"][1]["t_ns"]=200
        self.assertEqual(audit(x)["ordered_cap1_service_pairs"],0)
    def test_guest_not_clocked_or_guest_written_rejected(self):
        x=self.fixture()
        x["metadata"]["host_guest_register_writes"]=True
        with self.assertRaisesRegex(ValueError,"source-attributed"):
            audit(x)
        x=self.fixture()
        x["samples"][0]["sampling_qualifier"]="SAMPLED_HOLD_INTERVAL"
        with self.assertRaisesRegex(ValueError,"native clocked"):
            audit(x)
    def test_empty_or_non_monotonic_rejected(self):
        x=self.fixture()
        x["samples"][1]["t_ns"]=100
        with self.assertRaisesRegex(ValueError,"strictly increasing"):
            audit(x)
    def test_theoretical_crossings_are_bracketed_only(self):
        c=_threshold_crossings(self.fixture()["samples"])
        self.assertTrue(any(x["phase"]==0 and x["edge"]=="rising" for x in c))
        self.assertTrue(all(x["time_precision"]==
            "WFI_BRACKET_ONLY_NOT_EXACT_ANALOG_EDGE" for x in c))

if __name__=="__main__":
    unittest.main(verbosity=2)
