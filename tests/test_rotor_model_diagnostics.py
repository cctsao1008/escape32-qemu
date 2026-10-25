import unittest
from tools.ci.rotor_model_diagnostics import diagnose

class RotorModelForensics(unittest.TestCase):
    def test_nonreciprocal_projection_is_evidence_not_success(self):
        d=diagnose(dict(detail=dict(electromagnetic_power_ratio_pe_over_pm=7,
               integrator='SAMPLED_HOLD_EULER_TWO_TERMINAL_RESET_CURRENT_AT_COMMUTATION',
               significant_direction_reversals=20)))
        self.assertEqual(d['sim_only_significant_direction_reversals'],20)
        self.assertTrue(d['nonreciprocal_legacy_model'])
        self.assertTrue(d['commutation_resets_inductive_current'])
        self.assertIn('OPEN_',d['status'])
    def test_missing_evidence_fails_closed(self):
        d=diagnose({})
        self.assertIsNone(d['sim_only_significant_direction_reversals'])
        self.assertEqual(d['strict_gate'],'UNCHANGED_FAIL_UNLESS_EXTENDED_NATIVE_GATE_PASSES')
