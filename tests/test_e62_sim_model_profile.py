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
        self.assertEqual(
            r["independent_initial_electrical_phase_grid_deg"],
            [-150,-90,-30,30,90,150])
        self.assertTrue(r["initial_phase_is_qemu_model_only_not_guest_sensor"])
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

    def test_uv_ov_thermal_are_explicitly_unmodeled_not_pass(self):
        d=load()
        expected={"uv":"NOT_MODELED","ov":"NOT_MODELED",
                  "thermal":"NOT_MODELED"}
        self.assertEqual(
            d["protection_study"]["non_oc_virtual_fault_sources"],expected)
        self.assertEqual(
            report(d)["protection_source_status"]["thermal"],"NOT_MODELED")
        self.assertFalse(report(d)["unmodeled_faults_qualified"])
        for name in expected:
            forged=load()
            forged["protection_study"]["non_oc_virtual_fault_sources"][name]="PASS"
            with self.assertRaisesRegex(ValueError,"waive"):
                changed_doc(forged)
        forged=load()
        forged["protection_study"]["unmodeled_faults_claimed_qualified"]=True
        with self.assertRaisesRegex(ValueError,"waive"):
            changed_doc(forged)

    def test_rearm_and_scan_grid_mutations_rejected(self):
        d=load()
        d["passive_reacquisition_study"]["output_may_authorize_rearm"]=True
        with self.assertRaisesRegex(ValueError,"Unsafe"):
            changed_doc(d)
        d=load()
        d["passive_reacquisition_study"]["rpm_grid"]=[300,20]
        with self.assertRaisesRegex(ValueError,"Unsafe"):
            changed_doc(d)

    def test_unsafe_or_duplicate_initial_phase_profiles_rejected(self):
        d=load()
        d["passive_reacquisition_study"]["initial_electrical_degrees_grid"]=[
            -181,-30,90]
        with self.assertRaisesRegex(ValueError,"Unsafe passive"):
            changed_doc(d)
        d=load()
        d["passive_reacquisition_study"]["initial_electrical_degrees_grid"]=[
            -30,-30,90]
        with self.assertRaisesRegex(ValueError,"Unsafe passive"):
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

    def test_native_initial_electrical_pose_is_bounded_and_read_back(self):
        machine=(ROOT/"machine/am13e23019.c").read_text()
        plant=(ROOT/"machine/am13e_native_motor_plant.inc").read_text()
        runner=(ROOT/"tests/e62_autonomous_native_motor_probe.py").read_text()
        for token in ("esc-sim-native-initial-electrical-deg",
                      "degrees < -180 || degrees > 180",
                      "initial_phase_override"):
            self.assertIn(token,machine)
        for token in ("case 0xa0:", "initial_phase_override",
                      "-30000", "AM13E_NATIVE_MOTOR_SIZE 0xb4U"):
            self.assertIn(token,plant)
        self.assertIn("configured_initial_electrical_mdeg",runner)
        self.assertIn("args.sim_initial_electrical_degrees",runner)
        self.assertIn("initial_degrees*1000",runner)

    def test_native_adc_opt_in_maps_actual_firmware_phase_socs(self):
        machine=(ROOT/"machine/am13e23019.c").read_text()
        motor=(ROOT/"machine/am13e_native_motor_plant.inc").read_text()
        runner=(ROOT/"tests/e62_autonomous_native_motor_probe.py").read_text()
        self.assertIn('"esc-sim-native-adc-bemf"',machine)
        self.assertIn('adc->instance == 0U ? 12U',machine)
        self.assertIn('adc->instance == 1U ? 2U : 5U',machine)
        self.assertIn('adc->instance == 1U ? 2U : 1U',machine)
        self.assertIn('adc->machine->esc_sim_native_adc_bemf && i == phase_soc',machine)
        self.assertIn('++m->phase_adc_publications[adc->instance]',machine)
        self.assertIn('m->faulted',machine)
        self.assertIn('case 0xb0:',motor)
        self.assertIn('AM13E_NATIVE_MOTOR_SIZE 0xb4U',motor)
        self.assertIn('"guest_adc_phase_eoc_from_plant"',runner)
        self.assertIn('args.sim_native_adc_bemf',runner)

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
