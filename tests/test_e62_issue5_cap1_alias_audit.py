"""Diagnostic-only independent CAP1 alias classification contract."""
import unittest
from tools.e62_issue5_cap1_alias_audit import classify_capture, crossings, audit

def ev(t,kind,data=(0,0,0,0,0,0)):
    return {"vns":t,"kind":kind,"data":data}

class SourceCaptureAliasTests(unittest.TestCase):
    def test_geometric_zero_capture_does_not_become_speed_alias(self):
        # ROTOR a=millirpm, b=millirad; angle crosses 0 at 0.5ms.
        rot=[ev(0,"ROTOR",(100000,-200,0,0,0,0)),
             ev(1_000_000,"ROTOR",(100000,200,0,0,0,0)),
             ev(2_000_000,"ROTOR",(100000,400,0,0,0,0))]
        geom={p:crossings(rot,p) for p in range(3)}
        cap=ev(500_000,"CAP1")
        row=classify_capture(cap,ev(500_000,"CMP_FILTER",(0,1,0,0,0,0)),
                             rot,geom,crossings(rot),[ev(501_000,"T12_LOAD")])
        self.assertEqual(row["classification"],"ANGLE_ZERO_CANDIDATE")
        self.assertFalse(row["possible_false_commutation_reference"])
        self.assertTrue(row["source_timg12_reloaded_within_5us"])

    def test_speed_reversal_capture_is_not_a_valid_geometry_reference(self):
        rot=[ev(0,"ROTOR",(100000,1000,0,0,0,0)),
             ev(1_000_000,"ROTOR",(-100000,1100,0,0,0,0))]
        geom={p:crossings(rot,p) for p in range(3)}
        cap=ev(500_000,"CAP1")
        row=classify_capture(cap,ev(500_000,"CMP_FILTER",(0,1,0,0,0,0)),
                             rot,geom,crossings(rot),[ev(501_000,"T12_LOAD")])
        self.assertEqual(row["classification"],"SPEED_ZERO_ALIAS_CANDIDATE")
        self.assertTrue(row["possible_false_commutation_reference"])
        self.assertIsNone(row["angle_zero_distance_ms"])

    def test_missing_t12_does_not_claim_accepted_alias(self):
        rot=[ev(0,"ROTOR",(100000,1000,0,0,0,0)),
             ev(1_000_000,"ROTOR",(-100000,1100,0,0,0,0))]
        cap=ev(500_000,"CAP1")
        row=classify_capture(cap,ev(500_000,"CMP_FILTER",(0,1,0,0,0,0)),
                             rot,{p:crossings(rot,p) for p in range(3)},
                             crossings(rot),[])
        self.assertEqual(row["classification"],"SPEED_ZERO_ALIAS_CANDIDATE")
        self.assertFalse(row["possible_false_commutation_reference"])

    def test_ambiguous_speed_and_angle_is_not_claimed_as_reacquisition(self):
        rot=[ev(0,"ROTOR",(100000,-200,0,0,0,0)),
             ev(1_000_000,"ROTOR",(-100000,200,0,0,0,0))]
        cap=ev(500_000,"CAP1")
        row=classify_capture(cap,ev(500_000,"CMP_FILTER",(0,1,0,0,0,0)),
                             rot,{p:crossings(rot,p) for p in range(3)},
                             crossings(rot),[ev(502_000,"T12_LOAD")])
        self.assertEqual(row["classification"],"AMBIGUOUS_BOTH")
        self.assertTrue(row["possible_false_commutation_reference"])

    def test_source_provenance_fails_closed_before_data_processing(self):
        with self.assertRaisesRegex(ValueError,"ELF SHA"):
            audit([],{"original_elf_sha256":"invalid"},{})
        with self.assertRaisesRegex(ValueError,"MCPWM200"):
            audit([],{"original_elf_sha256":
                      "05563b6931b58aaba1df5105313c36c9de2d5797a0a3b190c86777c5773f13c0",
                      "host_guest_register_writes":False,
                      "used_guest_wfi_or_gdb":False,
                      "synthetic_timed_bemf_enabled":False},{})
if __name__=="__main__":
    unittest.main()
