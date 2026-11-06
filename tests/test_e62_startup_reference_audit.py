"""Synthetic unit records only; never qualification measurements."""
import unittest
from tools.e62_startup_reference_audit import analyze
class StartupReplayTests(unittest.TestCase):
    def test_stale_boundary_sample_keeps_its_age_and_gate_incomplete(self):
        es=[dict(kind='ROTOR',vns=5,a=0,b=0),dict(kind='DSHOT',vns=100,a=1)]
        r=analyze(es,[],{},1)
        self.assertEqual(r['preceding_sample_age_ns'],95)
        self.assertEqual(r['boundary_instantaneous_gate_state'],'INCOMPLETE_BOUNDED_SWITCH_LOG')
        self.assertEqual(r['startup_verdict'],'INCOMPLETE_NOT_QUALIFIED')
    def test_raw_capture_is_not_invented_firmware_acceptance(self):
        es=[dict(kind='DSHOT',vns=100,a=1),dict(kind='CAP1',seq=1,vns=120,a=30,b=0),dict(kind='ROTOR',vns=150,a=-51000)]
        r=analyze(es,[],{},1)
        self.assertEqual(r['startup_verdict'],'FAILED_SIGNIFICANT_REVERSAL')
        self.assertEqual(r['first_two_firmware_decisions'],[])
        self.assertIsNone(r['first_commutation_irq'])
        self.assertEqual(r['reference_observations_bracketing_reversal'],{})
        self.assertFalse(r['p1_qualified'])
    def test_missing_dshot_anchor_is_not_host_time_substitution(self):
        with self.assertRaises(StopIteration):analyze([],[],{},99)
if __name__=='__main__':unittest.main()
