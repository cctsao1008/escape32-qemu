"""E62 SIM_ONLY profiles: strict config, QEMU effective readback, negative gates."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from tools.e62_sim_profile_contract import load,report,DEFAULT
from tools.native_motor_model_profiles import DATASHEET_PROFILES
from tools.native_p1_oc_fault_plan import load_oc_plan

ROOT=Path(__file__).resolve().parents[1]

def changed_doc(data):
    with tempfile.TemporaryDirectory() as tmp:
        f=Path(tmp)/"profile.json"
        f.write_text(json.dumps(data))
        return load(f)

class SimModelProfileContract(unittest.TestCase):
    def test_both_profiles_match_existing_qemu_and_python_motor_source(self):
        d=load()
        self.assertEqual(set(d["profiles"]),set(DATASHEET_PROFILES))
        self.assertEqual(d["motor_plant_simulation"]["tick_ns"],1000)
        r=report(d)
        self.assertEqual(len(r["computed_points"]),10)
        self.assertFalse(r["rearm_permitted"])
        self.assertFalse(r["hardware_qualified"])

    def test_quantization_and_1khz_diag_alias_report_real_constraints(self):
        r=report(load())
        for profile in DATASHEET_PROFILES:
            points=[x for x in r["computed_points"] if x["profile"]==profile]
            low=next(x for x in points if x["mechanical_rpm"]==20)
            high=next(x for x in points if x["mechanical_rpm"]==300)
            self.assertTrue(low["model_BEMF_peak_below_requested_code_contrast"])
            self.assertTrue(high["model_diagnostic_at_risk_of_phase_rank_alias"])
            self.assertFalse(high["static_phase_rank_confidence_established"])

    def test_mutated_motor_gain_fails_closed(self):
        d=load()
        d["profiles"]["ecx87-kv210"]["terminal_kt_nm_per_a"]=0.0649
        with self.assertRaisesRegex(ValueError,"model"):
            changed_doc(d)

    def test_timing_diagnostic_cannot_claim_real_adc(self):
        d=load()
        d["analog_frontend_simulation"]["diagnostic_is_adc_sampling_clock"]=True
        with self.assertRaisesRegex(ValueError,"cannot impersonate"):
            changed_doc(d)

    def test_forged_current_model_and_trip_waiver_rejected(self):
        d=load()
        d["current_sensor_simulation"]["adc_codes_per_abs_amp"]=5
        with self.assertRaisesRegex(ValueError,"current/OC"):
            changed_doc(d)
        d=load()
        d["protection_study"]["trip_latch_retention_required"]=False
        with self.assertRaisesRegex(ValueError,"waive"):
            changed_doc(d)

    def test_rearm_and_scan_grid_mutations_rejected(self):
        d=load()
        d["passive_reacquisition_study"]["output_may_authorize_rearm"]=True
        with self.assertRaisesRegex(ValueError,"Unsafe"):
            changed_doc(d)
        d=load()
        d["passive_reacquisition_study"]["rpm_grid"]=[300,20]
        with self.assertRaisesRegex(ValueError,"Unsafe"):
            changed_doc(d)

    def test_unknown_profile_and_schema_fields_rejected(self):
        d=load()
        d["profiles"]["magic-motor"]=d["profiles"]["ecx87-kv147"]
        with self.assertRaisesRegex(ValueError,"unexpected motor"):
            changed_doc(d)
        d=load()
        d["sim_override_original_p1"]=True
        with self.assertRaisesRegex(ValueError,"schema"):
            changed_doc(d)

    def test_qemu_source_has_both_effective_parameter_branches(self):
        machine=(ROOT/"machine/am13e23019.c").read_text()
        plant=(ROOT/"machine/am13e_native_motor_plant.inc").read_text()
        runner=(ROOT/"tests/e62_autonomous_native_motor_probe.py").read_text()
        for token in ('"ecx87-kv147"','"ecx87-kv210"',
                      'esc-sim-native-motor-profile','model_profile==210U'):
            self.assertIn(token,machine)
        for token in ('0.0454 : 0.0649','0.00000875 : 0.000024',
                      '0.0283 : 0.053','case 0x8c:', 'case 0x90:',
                      'case 0x94:','case 0x98:','case 0x9c:'):
            self.assertIn(token,plant)
        self.assertIn('_assert_effective_sim_model',runner)
        self.assertIn('effective_sim_profile',runner)

if __name__=="__main__":
    unittest.main()
