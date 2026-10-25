import unittest
from tools.ci.native_pwm_overlap_audit import audit

SOURCE="ORIGINAL_GUEST_WFI_INCREMENTAL_QEMU_INTERNAL_PWM_HISTORY"

def record(evs):
    return {"pwm_history":{"scope":SOURCE,"events":evs}}

def edge(seq,ns,mask,kind="QEMU_CLOCKED_AQ_DB_EDGE"):
    return {"sequence":seq,"virtual_ns":ns,"new_mask":mask,"kind":kind,
            "observed_at_native_wfi":2}

class NativePwmOverlapRegression(unittest.TestCase):
    def test_actual_g14_zero_callback_20ns_w_pair_overlap_is_not_waived(self):
        rows=[edge(1587,13869071860,56,"QEMU_ORIGINAL_PWM_ZERO_CALLBACK"),
              edge(1588,13869071860,56,"QEMU_SHADOW_ACTIVE_LOAD"),
              edge(1589,13869071880,16)]
        r=audit(record(rows))
        self.assertEqual(r["status"],"FAIL_QEMU_MODELED_PWM_COMPLEMENTARY_OVERLAP")
        self.assertEqual(r["overlap_event_count"],2)
        self.assertEqual(r["modeled_overlap_events"][1]["phases"],["W"])
        self.assertEqual(
            r["modeled_overlap_events"][1]["duration_until_next_QEMU_event_ns"],20)
        self.assertTrue(r["strict_rotor_failure_not_waived"])

    def test_clean_observed_trace_does_not_qualify_physical_gates(self):
        r=audit(record([edge(1,0,40),edge(2,20,16)]))
        self.assertEqual(r["status"],"NO_OVERLAP_IN_OBSERVED_QEMU_HISTORY_ONLY")
        self.assertFalse(r["silicon_mosfet_shootthrough_qualified"])

    def test_discontinuous_clocked_journal_is_invalid(self):
        r=audit(record([edge(5,1,8),edge(7,2,16)]))
        self.assertEqual(r["status"],"INVALID_TRACE_EVIDENCE")

    def test_no_history_never_claims_pass(self):
        self.assertEqual(audit({})["status"],"INVALID_TRACE_EVIDENCE")
