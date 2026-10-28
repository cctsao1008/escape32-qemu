#!/usr/bin/env python3
"""Negative-control tests for E62 original Guest porting readiness aggregator."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.e62_porting_readiness import audit,EvidenceError,ELF,to_markdown

def fixture():
    cases=[]
    for name in ("smoke","gentle","direct20","steps"):
        good=name in ("smoke","gentle")
        cases.append({
            "case":name,"status":"PASS_MMIO_SOURCE_CONTRACT","issues":[],
            "timg12_virtual_deadline_error_ns":0,
            "p1_unchanged_qualified":good,
            "p1_unchanged_original_verdict":(
              "PASS_P1_SIM_ONLY_OBSERVABILITY" if good else
              "FAIL_P1_SIM_ONLY_OBSERVABILITY"),
            "first_cap1_did_not_observably_arm_timer":not good,
            "first_then_second_capture_arm_pattern_observed":not good
        })
    return {
        "p0":{"status":"PASS_SOURCE_MMIO_P0_SIM_ONLY","issues":[],
            "original_elf_sha256":ELF,"no_guest_intervention":True,
            "source_clock":"QEMU_CLOCK_VIRTUAL",
            "hardware_qualified":False,"p1_stability_not_tested":True,
            "matched_cap1_ack_guest_read":824,
            "matched_original_guest_timer_start_zero":824,
            "max_absolute_timer_deadline_error_ns":2},
        "p1":{"status":"PASS_MMIO_DIAGNOSTIC_NOT_P1_ACCEPTANCE",
            "p0_p1_gates_unchanged":True,"qualified_hardware":False,
            "scope":"SIM_ONLY","cases":cases},
        "crc":{"status":"PASS_ORIGINAL_GUEST_PHYSICAL_BAD_CRC_REJECTED",
            "issues":[],"scope":
            "PHYSICAL_PA26_DSHOT600_SOURCE_CRC_AND_WWDT_FEED_ONLY",
            "input_loss_watchdog_reset":"OPEN_NOT_MODELED",
            "physical_rotor_safety":"NOT_QUALIFIED"},
        "neutral_fault":{
            "status":"PASS_SIM_ONLY_EXTERNAL_FAULT_IRQ_SHUTDOWN_ONLY",
            "issues":[],"independent_cases_passed":[
                "nfault","oc-u","oc-v","oc-w"],
            "scope":"MODEL_ONLY_NATIVE_NEUTRAL_NOT_MOTOR_RUNNING",
            "real_power_stage":"NOT_QUALIFIED"},
        "inflight_fault":{
            "status":"PASS_P1_NATIVE_IN_FLIGHT_NFAULT_SAFE_OFF",
            "qualified":True,"failures":[],"source_fault_edges":2,
            "source_latched_ost2_at_fault":True,
            "final_OST2_latched":True,"final_gate_off":True,
            "original_guest_never_halted_or_injected":True,
            "original_guest_crc_feeds":2005,"external_DShot_continuity":3000,
            "scope":"SIM_ONLY_NFAULT_NEGATIVE_FAULT_RELEASE_NOT_RECOVERY",
            "automatic_rearm_and_flight_recovery_qualified":False,
            "electrical_hardware_qualified":False}
    }

class TestReadiness(unittest.TestCase):
    def test_good_sources_report_only_bounded_sim_scope(self):
        r=audit(fixture())
        self.assertEqual(r["status"],
              "PASS_BOUNDED_SITL_PORTING_EVIDENCE_WITH_OPEN_ITEMS")
        self.assertFalse(r["porting_complete"])
        self.assertFalse(r["hardware_qualified"])
        self.assertFalse(r["motor_p1_all_cases_qualified"])
        self.assertFalse(r["guest_capture_reject_private_return_observed"])
        self.assertEqual(r["p0_mmio"]["cap1_guest_read_chains"],824)
        self.assertEqual(r["p0_mmio"]["max_virtual_timer_error_ns"],2)
        md=to_markdown(r)
        self.assertIn("direct20 | PASS_MMIO_SOURCE_CONTRACT | FAIL",md)
        self.assertIn("Hardware",md.replace("hardware","Hardware"))
    def test_absent_evidence_rejected(self):
        data=fixture()
        del data["crc"]
        with self.assertRaisesRegex(EvidenceError,"missing independent"):
            audit(data)
    def test_strict_original_elf_identity(self):
        data=fixture();data["p0"]["original_elf_sha256"]="x"*64
        with self.assertRaisesRegex(EvidenceError,"p0 guest source identity"):
            audit(data)
    def test_fake_hardware_qualification_rejected(self):
        data=fixture();data["p1"]["qualified_hardware"]=True
        with self.assertRaisesRegex(EvidenceError,"p1 scope"):
            audit(data)
    def test_fast_direct20_failure_cannot_be_waived(self):
        data=fixture();case=data["p1"]["cases"][2]
        case["p1_unchanged_qualified"]=True
        with self.assertRaisesRegex(EvidenceError,"direct20 original motor P1 FAIL"):
            audit(data)
    def test_first_second_cap1_guest_timer_pattern_required(self):
        data=fixture()
        data["p1"]["cases"][3]["first_then_second_capture_arm_pattern_observed"]=False
        with self.assertRaisesRegex(EvidenceError,"steps first/second"):
            audit(data)
    def test_all_virtual_deadlines_are_checked(self):
        data=fixture();data["p1"]["cases"][0]["timg12_virtual_deadline_error_ns"]=21
        with self.assertRaisesRegex(EvidenceError,"smoke lacks independent"):
            audit(data)
        data=fixture();data["p0"]["max_absolute_timer_deadline_error_ns"]=25
        with self.assertRaisesRegex(EvidenceError,"p0 cap1/timer"):
            audit(data)
    def test_crc_watchdog_loss_not_fake_qualified(self):
        data=fixture();data["crc"]["input_loss_watchdog_reset"]="PASS"
        with self.assertRaisesRegex(EvidenceError,"DShot source proof"):
            audit(data)
    def test_neutral_safety_not_running_motor(self):
        data=fixture()
        data["neutral_fault"]["scope"]="RUNNING_NATIVE_MOTOR_QUALIFIED"
        with self.assertRaisesRegex(EvidenceError,"neutral OC"):
            audit(data)
    def test_nfault_recovery_not_fake_pass(self):
        data=fixture()
        data["inflight_fault"]["automatic_rearm_and_flight_recovery_qualified"]=True
        with self.assertRaisesRegex(EvidenceError,"in-flight no-WFI"):
            audit(data)
    def test_no_guest_synthetic_or_intervention(self):
        data=fixture();data["p0"]["no_guest_intervention"]=False
        with self.assertRaisesRegex(EvidenceError,"p0 guest source identity"):
            audit(data)

if __name__=="__main__":
    unittest.main(verbosity=2)
