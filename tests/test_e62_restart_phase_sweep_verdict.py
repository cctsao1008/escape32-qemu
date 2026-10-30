"""E62 #5 fail-closed initial electrical phase counterfactual provenance."""
import copy
import unittest
from tools.e62_restart_phase_sweep_verdict import evidence_errors
from tools.e62_sim_profile_contract import load

SOURCE="a"*64
PROFILE="ecx87-kv147"
def data():
    param=dict(kv_rpm_per_v=147,phase_resistance_microohm=53000,
               phase_inductance_nanohenry=24000,
               terminal_kt_micro_nm_per_a=64900,bus_millivolts=24000,
               configured_initial_electrical_mdeg=-30000)
    e={"original_elf_sha256":
       "05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0",
       "experimental_candidate_not_original":False,
       "host_guest_register_writes":False,
       "used_guest_wfi_or_gdb":False,
       "synthetic_timed_bemf_enabled":False,
       "native_dshot_scenario":{"sha256":SOURCE},
       "configured_dshot_frames":5100,
       "autonomous_dshot":{"sent":5100},
       "effective_sim_profile":{
           "name":PROFILE,"checked_against_named_model":True,
           "effective_parameters":param},
       "motor_before":{"effective_sim_motor_model":param.copy()}}
    return e,dict(sha256=SOURCE,dshot_frames=5100)

def check(e,m,profile=PROFILE,phase=-30):
    return evidence_errors(
        e,m,profile,phase,load()["passive_reacquisition_study"])

class RestartPhaseActualSourceProvenance(unittest.TestCase):
    def test_good_source_is_only_a_provenance_gate_not_rotor_pass(self):
        e,m=data()
        self.assertEqual(check(e,m),[])

    def test_invalid_or_forged_initial_pose_fails(self):
        e,m=data()
        e["effective_sim_profile"]["effective_parameters"][
            "configured_initial_electrical_mdeg"]=90000
        self.assertIn("QEMU_INITIAL_PHASE_OR_MOTOR_EFFECTIVE_READBACK_MISMATCH",
                      check(e,m))
        e,m=data()
        self.assertIn("INITIAL_ELECTRICAL_PHASE_NOT_IN_VERSIONED_GRID",
                      check(e,m,phase=91))

    def test_fake_guest_sensor_or_old_startup_not_accepted(self):
        e,m=data()
        e["experimental_candidate_not_original"]=True
        self.assertIn("NOT_IMMUTABLE_ORIGINAL_REL17_GUEST",check(e,m))
        e,m=data()
        e["host_guest_register_writes"]=True
        self.assertTrue(check(e,m))
        e,m=data()
        e["synthetic_timed_bemf_enabled"]=True
        self.assertTrue(check(e,m))

    def test_wrong_source_identity_missing_frames_fail(self):
        e,m=data()
        e["native_dshot_scenario"]["sha256"]="fake"
        self.assertIn("QEMU_EXTERNAL_FC_SCENARIO_SHA_CHANGED",check(e,m))
        e,m=data()
        e["autonomous_dshot"]["sent"]=5099
        self.assertIn("QEMU_NATIVE_DSHOT_SOURCE_INCOMPLETE",check(e,m))

    def test_named_profile_without_numeric_qtest_is_rejected(self):
        e,m=data()
        e["motor_before"]["effective_sim_motor_model"]={**e[
            "motor_before"]["effective_sim_motor_model"],"bus_millivolts":0}
        self.assertIn("QEMU_INITIAL_PHASE_OR_MOTOR_EFFECTIVE_READBACK_MISMATCH",
                      check(e,m))
        e,m=data()
        e["effective_sim_profile"]["checked_against_named_model"]=False
        self.assertTrue(check(e,m))

if __name__=="__main__":
    unittest.main()
