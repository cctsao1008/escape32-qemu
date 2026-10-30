#!/usr/bin/env python3
"""E62 #5 versioned profile registry: no firmware editing, no P1 waivers."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.e62_sim_case_profiles import load,resolve,verify_readback,_PROFILE_MAP

class TestE62CaseProfiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=load()
    def test_five_profiles_three_coasts_genuine_unchanged_guest(self):
        self.assertEqual(len(self.data["profiles"]),5)
        self.assertEqual(len(self.data["scenarios"]),3)
        self.assertEqual([s["coast_ms"] for s in self.data["scenarios"]],
                         [300,1500,3000])
        for name in _PROFILE_MAP:
            for coast in (300,1500,3000):
                p=resolve(self.data,name,coast)
                self.assertFalse(p["guest_motor_permission_from_profile"])
                self.assertTrue(p["original_p1_unchanged"])
                self.assertTrue(p["simulation_only"])
                self.assertEqual(p["expected_dshot_frames"],4800+coast)
    def test_24v_baselines_preserved_47v_analytical_separate(self):
        for p in self.data["profiles"]:
            apc=p["id"].startswith("QB-")
            self.assertEqual(p["dc_bus_millivolts"],47000 if apc else 24000)
            self.assertEqual(p["propeller_model"]=="NO_PROPELLER",not apc)
            self.assertFalse(p["product_hardware_calibrated"])
            self.assertFalse(p["propeller_inertia_measured"])
    def test_unsafe_profile_changes_rejected(self):
        for key,value in [
            ("dc_bus_millivolts",24000),
            ("guest_motor_permission_from_profile",True),
            ("effective_total_inertia_nano_kg_m2",130000),
            ("source_identity","REAL_HARDWARE_TEST")]:
            d=copy.deepcopy(self.data)
            d["profiles"][3][key]=value
            with tempfile.TemporaryDirectory() as root:
                f=Path(root)/"unsafe.json";f.write_text(json.dumps(d))
                with self.assertRaises(ValueError):
                    load(f)
    def test_p1_waiver_and_scenario_forgery_rejected(self):
        for field,value in [
            ("original_p1_criteria_unchanged",False),
            ("guest_rotor_angle_injection",True),
            ("hardware_qualified",True)]:
            d=copy.deepcopy(self.data)
            d["source_contract"][field]=value
            with tempfile.TemporaryDirectory() as root:
                f=Path(root)/"unsafe.json";f.write_text(json.dumps(d))
                with self.assertRaises(ValueError):
                    load(f)
        d=copy.deepcopy(self.data)
        d["scenarios"][0]["expected_dshot_frames"]=100
        with tempfile.TemporaryDirectory() as root:
            f=Path(root)/"unsafe.json";f.write_text(json.dumps(d))
            with self.assertRaises(ValueError):
                load(f)
    def test_readback_failure_cannot_become_a_restart_pass(self):
        p=resolve(self.data,"QB-KV210-47V-APC24X12E-J2",300)
        invalid=verify_readback(p,{})
        self.assertFalse(invalid["source_profile_readback_pass"])
        self.assertFalse(invalid["original_p1_qualified_by_profile"])
        self.assertFalse(invalid["hardware_qualified"])
        self.assertIn("EFFECTIVE_MODEL_READBACK_MISMATCH",invalid["failures"])
    def test_extra_unknown_profile_disallowed(self):
        d=copy.deepcopy(self.data)
        d["profiles"].append(copy.deepcopy(d["profiles"][-1]))
        with tempfile.TemporaryDirectory() as root:
            f=Path(root)/"unsafe.json";f.write_text(json.dumps(d))
            with self.assertRaises(ValueError):
                load(f)

if __name__=="__main__":
    unittest.main()
